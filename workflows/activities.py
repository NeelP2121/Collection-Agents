from agents.agent1_assessment import run_agent1
from agents.agent2_resolution import run_agent2
from agents.agent3_final_notice import run_agent3
from summarizer.summarizer import Summarizer

summarizer = Summarizer()

async def run_assessment_agent(borrower):
    return run_agent1(borrower)

async def summarize_chat(conversation):
    return summarizer.summarize(conversation, "agent1")

async def run_voice_agent(handoff):
    return run_agent2(handoff)

async def summarize_combined(data):
    return summarizer.summarize(data, "agent2")

async def run_final_agent(handoff):
    return run_agent3(handoff)
