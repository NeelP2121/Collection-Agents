import json
from utils.llm import call_llm
from summarizer.token_counter import TokenCounter, enforce_handoff_budget
from utils.config import LLM_MODELS

class Summarizer:
    def __init__(self):
        self.token_counter = TokenCounter()

    def summarize_agent1_to_agent2(self, conversation_history, borrower_context):
        """
        Summarize Agent 1 chat conversation for Agent 2 voice handoff.
        Must preserve: identity verification status, financial details, hardship indicators,
        borrower personality/resistance level, key objections, settlement interest.
        Max 500 tokens.
        """
        
        system_prompt = f"""You are a handoff summarizer for a debt collections AI system.
        
        Summarize the Agent 1 (chat assessment) conversation into a structured JSON handoff for Agent 2 (voice resolution).
        
        CRITICAL: Preserve all information needed for Agent 2 to continue seamlessly:
        - Borrower identity verification status
        - Financial situation and hardship indicators  
        - Borrower personality (cooperative/hostile/evasive)
        - Key objections or concerns raised
        - Interest in settlement/payment options
        - Any commitments or agreements made
        - Communication preferences
        
        Structure the summary as JSON with these exact keys:
        {{
            "borrower_profile": "Brief personality assessment",
            "identity_verified": boolean,
            "financial_summary": "Key financial details and hardship",
            "key_objections": ["list", "of", "objections"],
            "settlement_interest": "Level of interest shown",
            "communication_notes": "Any special communication needs",
            "recommended_approach": "Suggested strategy for Agent 2"
        }}
        
        Keep total tokens under 500. Be concise but comprehensive."""

        conversation_text = "\n".join([
            f"Agent: {msg.get('agent', '')}" if msg.get('role') == 'assistant' else f"Borrower: {msg.get('content', '')}"
            for msg in conversation_history
        ])
        
        context_info = f"""
        Borrower Context:
        - Name: {borrower_context.get('borrower_name', 'Unknown')}
        - Phone: {borrower_context.get('phone', 'Unknown')}
        - Current Stage: {borrower_context.get('stage', 'Unknown')}
        - Identity Verified: {borrower_context.get('identity_verified', False)}
        - Hardship Detected: {borrower_context.get('hardship_detected', False)}
        """
        
        full_input = f"{context_info}\n\nConversation:\n{conversation_text}"
        
        response = call_llm(
            system=system_prompt,
            messages=[{"role": "user", "content": full_input}],
            model=LLM_MODELS["evaluation"]  # Use Haiku for summarization
        )
        
        # Enforce token budget
        summary_text, token_count = enforce_handoff_budget(response)
        
        try:
            summary = json.loads(summary_text)
        except json.JSONDecodeError:
            # Fallback to text summary if JSON parsing fails
            summary = {
                "borrower_profile": "Unknown",
                "identity_verified": borrower_context.get('identity_verified', False),
                "financial_summary": summary_text[:200],
                "key_objections": [],
                "settlement_interest": "Unknown",
                "communication_notes": "",
                "recommended_approach": "Standard collection approach"
            }
        
        return summary

    def summarize_agent2_to_agent3(self, combined_data, borrower_context):
        """
        Summarize Agent 2 voice conversation + Agent 1 summary for Agent 3 final notice handoff.
        Must preserve: all previous context, voice call outcomes, settlement offers made,
        borrower responses, escalation readiness.
        Max 500 tokens.
        """
        
        system_prompt = f"""You are a handoff summarizer for a debt collections AI system.
        
        Summarize the combined Agent 1 chat + Agent 2 voice interactions into a structured JSON handoff for Agent 3 (final notice).
        
        CRITICAL: Preserve all information needed for Agent 3 final escalation:
        - Complete borrower profile and history
        - All settlement offers made and responses
        - Voice call outcomes and borrower reactions
        - Hardship status and assistance offered
        - Compliance with all FDCPA rules
        - Recommended final notice strategy
        
        Structure the summary as JSON with these exact keys:
        {{
            "borrower_history": "Complete background from both agents",
            "settlement_offers": ["list", "of", "offers", "made"],
            "borrower_responses": "How borrower reacted to offers",
            "voice_call_outcome": "Result of voice interaction",
            "hardship_status": "Current hardship assessment",
            "compliance_status": "Any violations or concerns",
            "final_strategy": "Recommended approach for final notice"
        }}
        
        Keep total tokens under 500. Be concise but comprehensive."""

        # Combine Agent 1 summary + Agent 2 conversation
        agent1_summary = combined_data.get('agent1_handoff', {})
        agent2_conversation = combined_data.get('agent2_conversation', [])
        
        context_info = f"""
        Borrower Context:
        - Name: {borrower_context.get('borrower_name', 'Unknown')}
        - Phone: {borrower_context.get('phone', 'Unknown')}
        - Current Stage: {borrower_context.get('stage', 'Unknown')}
        - Identity Verified: {borrower_context.get('identity_verified', False)}
        - Hardship Detected: {borrower_context.get('hardship_detected', False)}
        
        Agent 1 Summary: {json.dumps(agent1_summary)}
        
        Agent 2 Conversation:
        {json.dumps(agent2_conversation)}
        """
        
        response = call_llm(
            system=system_prompt,
            messages=[{"role": "user", "content": context_info}],
            model=LLM_MODELS["evaluation"]  # Use Haiku for summarization
        )
        
        # Enforce token budget
        summary_text, token_count = enforce_handoff_budget(response)
        
        try:
            summary = json.loads(summary_text)
        except json.JSONDecodeError:
            # Fallback to text summary if JSON parsing fails
            summary = {
                "borrower_history": summary_text[:200],
                "settlement_offers": [],
                "borrower_responses": "Unknown",
                "voice_call_outcome": "Unknown",
                "hardship_status": "Unknown",
                "compliance_status": "Unknown",
                "final_strategy": "Standard final notice"
            }
        
        return summary

    # Legacy method for backward compatibility
    def summarize(self, conversation, stage):
        """Legacy summarization method"""
        if stage == "agent1":
            return self.summarize_agent1_to_agent2(conversation, {})
        elif stage == "agent2":
            return self.summarize_agent2_to_agent3({"agent2_conversation": conversation}, {})
        else:
            return {"summary": "Unknown stage"}