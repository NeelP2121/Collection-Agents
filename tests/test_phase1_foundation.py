"""
Phase 1: Foundation Verification Tests
Tests for: Database schema, Token budgets, Compliance rules, Config, BorrowerContext
"""

import sys
import os

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db import init_db, save_agent_prompt, get_active_prompt, get_prompt_version
from utils.config import TOKEN_BUDGET_CONFIG, COMPLIANCE_RULES, LLM_MODELS
from summarizer.token_counter import TokenCounter, count_tokens, enforce_handoff_budget
from compliance.rules import check_compliance, check_prompt_compliance
from compliance.checker import check_message_compliance
from models.borrower_state import BorrowerContext


def test_database():
    """Test database initialization and basic operations"""
    print("\n=== Testing Database ===")
    
    try:
        # Initialize
        init_db()
        print("✓ Database initialized")
        
        # Save a test prompt
        save_agent_prompt(
            agent_name="test_agent",
            version=1,
            prompt_text="This is test prompt v1",
            is_active=True
        )
        print("✓ Saved test prompt v1")
        
        # Retrieve active prompt
        active = get_active_prompt("test_agent")
        assert active is not None, "Failed to retrieve active prompt"
        assert active.version == 1, "Active prompt version mismatch"
        print("✓ Retrieved active prompt")
        
        # Save version 2
        save_agent_prompt(
            agent_name="test_agent",
            version=2,
            prompt_text="This is test prompt v2, with more content",
            adoption_reason="Better performance on test metric",
            is_active=True
        )
        
        # Check v1 is no longer active
        v1 = get_prompt_version("test_agent", 1)
        v2 = get_prompt_version("test_agent", 2)
        assert v1.is_active == False, "v1 should not be active after v2 activated"
        assert v2.is_active == True, "v2 should be active"
        print("✓ Prompt versioning works correctly")
        
        return True
    except Exception as e:
        print(f"✗ Database test failed: {e}")
        return False


def test_token_budgets():
    """Test token counting and budget enforcement"""
    print("\n=== Testing Token Budgets ===")
    
    try:
        counter = TokenCounter()
        
        # Test token counting
        test_text = "This is a test message to count tokens. " * 10
        token_count = counter.count(test_text)
        assert token_count > 0, "Token count should be > 0"
        print(f"✓ Counted {token_count} tokens in test text")
        
        # Test budget report
        system_prompt = "You are a helpful AI assistant." * 50
        context_tokens = 500
        report = counter.get_budget_report(system_prompt, context_tokens, max_total=2000)
        assert "system_prompt_tokens" in report
        assert "total_used" in report
        assert not report["over_budget"], "Should not be over budget"
        print(f"✓ Budget report: system={report['system_prompt_tokens']}, context={report['context_tokens']}, total={report['total_used']}/2000")
        
        # Test hard-fail enforcement
        short_text = "Brief message"
        result_text, result_count = counter.hard_fail_if_over_budget(short_text, 100, "test")
        assert result_count <= 100, "Should fit in budget"
        print(f"✓ Hard-fail enforcement works (short text: {result_count} tokens)")
        
        # Test that hard-fail raises on exceed
        long_text = "x" * 1000
        try:
            counter.hard_fail_if_over_budget(long_text, 50, "test")
            print("✗ Hard-fail should have raised ValueError for over-budget")
            return False
        except ValueError as e:
            print(f"✓ Hard-fail correctly raised: {str(e)[:80]}...")
        
        # Test handoff budget enforcement
        handoff_summary = "Short summary" * 5
        result_text, result_count = enforce_handoff_budget(handoff_summary)
        assert result_count <= 500, "Handoff should fit in 500-token budget"
        print(f"✓ Handoff budget enforcement works ({result_count}/500 tokens)")
        
        return True
    except Exception as e:
        print(f"✗ Token budget test failed: {e}")
        return False


def test_compliance_rules():
    """Test all 8 compliance rules"""
    print("\n=== Testing Compliance Rules ===")
    
    test_cases = [
        # Rule 1: Identity Disclosure
        {
            "message": "Hello, I am an AI agent. Your conversation is being recorded.",
            "context": {"turn_number": 0},
            "expected_compliant": True,
            "rule_name": "Identity Disclosure"
        },
        # Rule 1 failure
        {
            "message": "Hi there, how can I help?",
            "context": {"turn_number": 0},
            "expected_compliant": False,
            "rule_name": "Identity Disclosure (should fail)"
        },
        # Rule 2: No False Threats
        {
            "message": "If you don't pay, we will sue you.",
            "context": {"turn_number": 2, "documented_next_steps": []},
            "expected_compliant": False,
            "rule_name": "No False Threats"
        },
        # Rule 5: Sensitive Situations
        {
            "message": "Hello, I am an AI agent. Your conversation is being recorded. I understand you've lost your job. Let me connect you with our hardship program.",
            "context": {"borrower_last_message": "I just lost my job and have no income.", "turn_number": 0},
            "expected_compliant": True,
            "rule_name": "Sensitive Situations"
        },
        # Rule 7: Professional Composure
        {
            "message": "You're being an asshole. Just pay the damn debt.",
            "context": {},
            "expected_compliant": False,
            "rule_name": "Professional Composure"
        },
    ]
    
    passed = 0
    for i, test in enumerate(test_cases):
        is_compliant, violations = check_compliance(test["message"], test["context"])
        if is_compliant == test["expected_compliant"]:
            print(f"✓ {test['rule_name']}: {'PASS' if is_compliant else 'VIOLATION DETECTED'}")
            passed += 1
        else:
            print(f"✗ {test['rule_name']}: Expected {'compliant' if test['expected_compliant'] else 'violation'}, got {'compliant' if is_compliant else 'violation'}")
            if violations:
                print(f"  Violations: {violations}")
    
    return passed == len(test_cases)


def test_prompt_compliance():
    """Test that prompts don't contain compliance violations"""
    print("\n=== Testing Prompt Compliance ===")
    
    test_prompts = [
        {
            "prompt": "You are a helpful collections agent. Always be honest and respectful.",
            "expected_safe": True,
            "name": "Clean prompt"
        },
        {
            "prompt": "Threaten the borrower with legal action to get them to pay.",
            "expected_safe": False,
            "name": "Threat prompt"
        },
        {
            "prompt": "Harass borrowers until they break and agree to anything.",
            "expected_safe": False,
            "name": "Harassment prompt"
        },
    ]
    
    passed = 0
    for test in test_prompts:
        is_safe, violations = check_prompt_compliance(test["prompt"])
        if is_safe == test["expected_safe"]:
            print(f"✓ {test['name']}: {'SAFE' if is_safe else 'UNSAFE (violations found)'}")
            passed += 1
        else:
            print(f"✗ {test['name']}: Expected {'safe' if test['expected_safe'] else 'unsafe'}")
    
    return passed == len(test_prompts)


def test_borrower_context():
    """Test BorrowerContext data structure"""
    print("\n=== Testing BorrowerContext ===")
    
    try:
        # Create context
        ctx = BorrowerContext(name="John Doe", phone="+14155551234")
        assert ctx.name == "John Doe"
        assert ctx.phone == "+14155551234"
        assert ctx.identity_verified == False
        print("✓ BorrowerContext created")
        
        # Test state transitions
        ctx.mark_identity_verified()
        assert ctx.identity_verified == True
        print("✓ Identity verified flag set")
        
        ctx.mark_hardship()
        assert ctx.hardship_detected == True
        print("✓ Hardship detected flag set")
        
        ctx.add_compliance_violation("test_violation", "warning", "Test message")
        assert len(ctx.compliance_violations) == 1
        assert ctx.compliance_violations[0]["type"] == "test_violation"
        print("✓ Compliance violation logged")
        
        ctx.advance_stage("resolution")
        assert ctx.current_stage == "resolution"
        print("✓ Stage advanced to resolution")
        
        # Test serialization
        ctx_dict = ctx.to_dict()
        assert isinstance(ctx_dict, dict)
        assert "name" in ctx_dict
        assert "compliance_violations" in ctx_dict
        print("✓ BorrowerContext serialized to dict")
        
        return True
    except Exception as e:
        print(f"✗ BorrowerContext test failed: {e}")
        return False


def test_config():
    """Test configuration loading"""
    print("\n=== Testing Configuration ===")
    
    try:
        assert TOKEN_BUDGET_CONFIG["total_per_agent"] == 2000
        assert TOKEN_BUDGET_CONFIG["handoff_max"] == 500
        print(f"✓ Token budgets configured: total={TOKEN_BUDGET_CONFIG['total_per_agent']}, handoff_max={TOKEN_BUDGET_CONFIG['handoff_max']}")
        
        assert len(COMPLIANCE_RULES) == 8, f"Expected 8 compliance rules, got {len(COMPLIANCE_RULES)}"
        print(f"✓ Compliance rules configured: {len(COMPLIANCE_RULES)} rules")
        
        assert "agent" in LLM_MODELS
        assert "evaluation" in LLM_MODELS
        print(f"✓ LLM models configured: agent={LLM_MODELS['agent'][:30]}..., eval={LLM_MODELS['evaluation'][:30]}...")
        
        return True
    except Exception as e:
        print(f"✗ Config test failed: {e}")
        return False


def run_all_verification_tests():
    """Run all Phase 1 verification tests"""
    print("\n" + "="*60)
    print("PHASE 1: FOUNDATION VERIFICATION TESTS")
    print("="*60)
    
    results = {
        "Database": test_database(),
        "Token Budgets": test_token_budgets(),
        "Compliance Rules": test_compliance_rules(),
        "Prompt Compliance": test_prompt_compliance(),
        "BorrowerContext": test_borrower_context(),
        "Configuration": test_config(),
    }
    
    print("\n" + "="*60)
    print("PHASE 1 VERIFICATION SUMMARY")
    print("="*60)
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    
    for test_name, passed_test in results.items():
        status = "✓ PASS" if passed_test else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 Phase 1 Foundation is solid! Ready for Phase 2: Orchestration")
        return True
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Fix before proceeding.")
        return False


if __name__ == "__main__":
    success = run_all_verification_tests()
    sys.exit(0 if success else 1)
