from agents.agent1_assessment import run_agent1
from agents.agent3_final_notice import run_agent3
from summarizer.summarizer import Summarizer
from voice.voice_handler import VapiHandler

summarizer = Summarizer()
voice = VapiHandler()

async def run_assessment_agent(borrower):
    return run_agent1(borrower)

async def summarize_chat(conversation):
    return summarizer.summarize(conversation, "agent1")

async def initiate_voice_call(handoff):
    return voice.initiate_call(handoff["phone"], handoff)

async def summarize_combined(data):
    return summarizer.summarize(data, "agent2")

async def run_final_notice_agent(handoff):
    return run_agent3(handoff)
