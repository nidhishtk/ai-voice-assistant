from __future__ import annotations
import os
import asyncio
import json
import re
from typing import AsyncIterator, Optional

from dotenv import load_dotenv
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    llm,
    AgentSession,
    Agent
)
import google.generativeai as genai
from livekit.rtc.event_emitter import EventEmitter
from livekit.plugins.google import tts

from api import AssistantFnc
from prompts import INSTRUCTIONS, WELCOME_MESSAGE, LOOKUP_VIN_MESSAGE

load_dotenv()

# Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Initialize the Google TTS model
tts_model = tts.TTS()

# --- Custom ChatStream Implementation ---
class CustomChatStream:
    """
    Custom stream class to handle streaming responses.
    """
    def __init__(self):
        self._queue = asyncio.Queue()
        self._ended = False

    def push_delta(self, delta: str):
        """
        Push a text delta to the queue.
        """
        if not self._ended:
            asyncio.create_task(self._queue.put(delta))

    async def end_stream(self):
        """
        Mark the stream as ended and put a None sentinel to signal completion.
        """
        if not self._ended:
            self._ended = True
            await self._queue.put(None)

    async def __aiter__(self) -> AsyncIterator[str]:
        """
        Async iterator to yield text deltas.
        """
        while not self._ended:
            item = await self._queue.get()
            if item is None:
                break
            yield item

# --- Wrapper for ChatStream to support async with ---
class ChatStreamContext:
    """
    A wrapper to make CustomChatStream compatible with async with statement.
    """
    def __init__(self, stream: CustomChatStream):
        self._stream = stream

    async def __aenter__(self):
        return self._stream

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._stream.end_stream()

    async def __aiter__(self):
        async for chunk in self._stream:
            yield chunk

# --- Gemini LLM Wrapper ---
class GeminiLLMWrapper(llm.LLM, EventEmitter):
    def __init__(self, model_name: str):
        super().__init__()
        self._model = genai.GenerativeModel(model_name)

    def chat(self, chat_ctx: llm.ChatContext, **kwargs) -> ChatStreamContext:
        # Use messages from kwargs (passed from handle_user_speech)
        history = kwargs.get("messages", [])
        if not history:
            try:
                history = getattr(chat_ctx, "get_messages", lambda: [])()
            except AttributeError:
                pass

        # Convert history to Gemini-compatible format
        gemini_history = []
        for msg in history:
            role = "user" if msg.role == "user" else "model"
            content = msg.content[0] if isinstance(msg.content, list) else str(msg.content)
            gemini_history.append({"role": role, "parts": [content]})
            print(f"History: role={role}, content={content}")

        # Start chat with all but the last message as history
        chat_session = self._model.start_chat(history=gemini_history[:-1] if gemini_history else [])
        # Send the last message (if any) or the WELCOME_MESSAGE as default
        last_message = gemini_history[-1]["parts"][0] if gemini_history else WELCOME_MESSAGE
        print(f"Sending to Gemini: {last_message}")
        response_stream = chat_session.send_message_async(last_message, stream=True)
        
        stream_wrapper = CustomChatStream()

        async def _generate_chunks():
            try:
                print("Starting Gemini streaming")
                async for chunk_response in await response_stream:
                    for part in chunk_response.parts:
                        if part.text:
                            print(f"Pushing delta: {part.text}")
                            stream_wrapper.push_delta(part.text)
            except Exception as e:
                print(f"Error during Gemini streaming: {e}")
            finally:
                print("Ending stream")
                await stream_wrapper.end_stream()

        asyncio.create_task(_generate_chunks())
        return ChatStreamContext(stream_wrapper)

# Initialize the Gemini model for your agent
model = GeminiLLMWrapper(model_name="gemini-1.5-flash")

# --- LiveKit Agent Entrypoint ---
async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)
    await ctx.wait_for_participant()

    agent = Agent(
        instructions=INSTRUCTIONS,
        # tools=[] # Uncomment and define your tools here if using LLM function calling
    )

    session = AgentSession(llm=model, tts=tts_model)
    await session.start(room=ctx.room, agent=agent)

    # Initialize chat history with system instructions and welcome message
    chat_history = [
        llm.ChatMessage(role="system", content=[INSTRUCTIONS]),
        llm.ChatMessage(role="assistant", content=[WELCOME_MESSAGE])
    ]
    await session.say(WELCOME_MESSAGE)

    assistant = AssistantFnc()

    @session.on("user_speech_committed")
    def on_user_speech_committed(msg: llm.ChatMessage):
        asyncio.create_task(handle_user_speech(msg, session, chat_history, assistant))

# --- Handle User Speech ---
async def handle_user_speech(msg: llm.ChatMessage, session: AgentSession, chat_history: list, assistant: AssistantFnc):
    user_input = msg.content[0] if isinstance(msg.content, list) else msg.content.lower().strip()
    print(f"User input: {user_input}")
    chat_history.append(llm.ChatMessage(role="user", content=[user_input]))

    # Handle "no" response explicitly
    if user_input in ["no", "n", "nope", "don't have it"]:
        response = "No worries! We can look up your vehicle using your license plate number and state. Could you provide those details?"
        chat_history.append(llm.ChatMessage(role="assistant", content=[response]))
        await session.say(response)
        return

    if not assistant.has_car():
        lookup_message = LOOKUP_VIN_MESSAGE
        chat_history.append(llm.ChatMessage(role="system", content=[lookup_message]))
        print(f"System message: {lookup_message}")

    try:
        stream_context = model.chat(chat_ctx=llm.ChatContext(), messages=chat_history)
        full_response = ""

        async with stream_context as stream:
            async for chunk in stream:
                if chunk:
                    print(f"Received chunk: {chunk}")
                    full_response += chunk
                    session.response.delta(chunk)

        print(f"Full response: {full_response}")
        function_call = parse_function_call(full_response)
        
        if function_call:
            result = await execute_function_call(function_call, assistant)
            chat_history.append(llm.ChatMessage(role="assistant", content=[result]))
            session.response.message(result)
            print(f"Function call result: {result}")
        else:
            chat_history.append(llm.ChatMessage(role="assistant", content=[full_response]))
            session.response.message(full_response)

    except Exception as e:
        print(f"[Error] LLM processing failed: {e}")
        error_message = "Sorry, something went wrong."
        session.response.message(error_message)

# --- Function Calling Utilities ---
def parse_function_call(response: str) -> dict | None:
    try:
        match = re.search(r'\{.*"function":.*\}', response, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except json.JSONDecodeError:
        pass
    return None

async def execute_function_call(call: dict, assistant: AssistantFnc) -> str:
    func_name = call.get("function")
    args = call.get("arguments", {})

    if func_name == "lookup_car":
        return await assistant.lookup_car(args.get("vin", ""))
    elif func_name == "create_car_profile":
        return await assistant.create_car_profile(
            args.get("vin", ""),
            args.get("make", ""),
            args.get("model", ""),
            args.get("year", 0)
        )
    elif func_name == "lookup_car_by_license_plate":
        return await assistant.lookup_car_by_license_plate(
            args.get("license_plate", ""),
            args.get("state", "")
        )
    else:
        return f"Unknown function: {func_name}"

# --- Main Execution Block ---
if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))