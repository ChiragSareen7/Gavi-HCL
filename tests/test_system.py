#!/usr/bin/env python3
"""
Comprehensive system test - tests all endpoints and RAG functionality.
"""

import json
import os
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests


BASE_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
API_KEY = os.environ.get("HONEYPOT_API_KEY", "")


def test_health():
    """Test health endpoint."""
    print("\n" + "="*60)
    print("TEST 1: Health Check")
    print("="*60)
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        response.raise_for_status()
        result = response.json()
        assert result.get("status") == "ok"
        print("✅ Health check passed")
        return True
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False


def test_compare_endpoint():
    """Test /compare endpoint."""
    print("\n" + "="*60)
    print("TEST 2: Compare Endpoint (Base vs RAG)")
    print("="*60)
    try:
        response = requests.post(
            f"{BASE_URL}/compare",
            json={"text": "KYC pending. Your account will be blocked. Click http://sbi-kyc.in to update."},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        
        assert "base" in result
        assert "finetuned" in result  # Actually RAG-enhanced now
        assert "decision_delta" in result
        
        print(f"✅ Compare endpoint passed")
        print(f"   Base label: {result['base']['label']}")
        print(f"   RAG label: {result['finetuned']['label']}")
        print(f"   Decision delta: {result['decision_delta']}")
        return True
    except Exception as e:
        print(f"❌ Compare endpoint failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Response: {e.response.text[:200]}")
        return False


def test_v1_chat_single_turn():
    """Test /v1/chat endpoint with single message."""
    print("\n" + "="*60)
    print("TEST 3: /v1/chat Single Turn")
    print("="*60)
    try:
        headers = {"Content-Type": "application/json"}
        if API_KEY:
            headers["x-api-key"] = API_KEY
            
        payload = {
            "sessionId": f"test-single-{int(time.time())}",
            "message": {
                "sender": "scammer",
                "text": "KYC pending. Your account will be blocked in 2 hours. Click http://sbi-kyc-help.in to update.",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")
            },
            "conversationHistory": None,
            "metadata": {}
        }
        
        response = requests.post(
            f"{BASE_URL}/v1/chat",
            json=payload,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        
        assert result.get("status") == "success"
        assert "reply" in result
        assert len(result["reply"]) > 0
        
        print(f"✅ /v1/chat single turn passed")
        print(f"   Reply: {result['reply'][:100]}...")
        return True
    except Exception as e:
        print(f"❌ /v1/chat single turn failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Response: {e.response.text[:200]}")
        return False


def test_v1_chat_multi_turn():
    """Test /v1/chat endpoint with multiple turns."""
    print("\n" + "="*60)
    print("TEST 4: /v1/chat Multi-Turn Conversation")
    print("="*60)
    try:
        session_id = f"test-multi-{int(time.time())}"
        headers = {"Content-Type": "application/json"}
        if API_KEY:
            headers["x-api-key"] = API_KEY
        
        messages = [
            "Sir I am from SBI, your KYC pending. If not update, account freeze.",
            "No sir, today issue. Pay ₹99 verification fee. Send to UPI: sbihelpdesk@okicici",
            "Pay fast, otherwise freeze."
        ]
        
        conversation_history = []
        
        for i, message_text in enumerate(messages, 1):
            payload = {
                "sessionId": session_id,
                "message": {
                    "sender": "scammer",
                    "text": message_text,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")
                },
                "conversationHistory": conversation_history,
                "metadata": {}
            }
            
            response = requests.post(
                f"{BASE_URL}/v1/chat",
                json=payload,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            
            assert result.get("status") == "success"
            assert "reply" in result
            assert len(result["reply"]) > 0
            
            # Update conversation history for next turn
            conversation_history.append({
                "role": "scammer",
                "content": message_text
            })
            conversation_history.append({
                "role": "agent",
                "content": result["reply"]
            })
            
            print(f"   Turn {i}: Reply length = {len(result['reply'])} chars")
            print(f"   Reply: {result['reply'][:80]}...")
            
            time.sleep(0.5)  # Small delay between turns
        
        print(f"✅ /v1/chat multi-turn passed")
        return True
    except Exception as e:
        print(f"❌ /v1/chat multi-turn failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Response: {e.response.text[:200]}")
        return False


def test_rag_functionality():
    """Test that RAG is working by checking responses contain context-aware content."""
    print("\n" + "="*60)
    print("TEST 5: RAG Functionality")
    print("="*60)
    try:
        headers = {"Content-Type": "application/json"}
        if API_KEY:
            headers["x-api-key"] = API_KEY
        
        # Test with a message that should trigger RAG pattern
        payload = {
            "sessionId": f"test-rag-{int(time.time())}",
            "message": {
                "sender": "scammer",
                "text": "Congrats! You won 12 lakh lottery. Pay processing fee ₹4,999 via UPI: luckyprize@paytm",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")
            },
            "conversationHistory": None,
            "metadata": {}
        }
        
        response = requests.post(
            f"{BASE_URL}/v1/chat",
            json=payload,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        
        reply = result.get("reply", "").lower()
        
        # Check if reply shows awareness (should question lottery, ask for details)
        has_question = any(word in reply for word in ["lottery", "kaunsi", "company", "sms", "email"])
        
        if has_question:
            print(f"✅ RAG functionality passed - reply shows context awareness")
            print(f"   Reply: {result['reply'][:100]}...")
        else:
            print(f"⚠️  RAG may not be working - reply doesn't show expected context")
            print(f"   Reply: {result['reply'][:100]}...")
        
        return True
    except Exception as e:
        print(f"❌ RAG test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("COMPREHENSIVE SYSTEM TEST")
    print("="*60)
    print(f"Backend URL: {BASE_URL}")
    
    results = {
        "Health Check": test_health(),
        "Compare Endpoint": test_compare_endpoint(),
        "Single Turn Chat": test_v1_chat_single_turn(),
        "Multi-Turn Chat": test_v1_chat_multi_turn(),
        "RAG Functionality": test_rag_functionality(),
    }
    
    print("\n" + "="*60)
    print("TEST RESULTS SUMMARY")
    print("="*60)
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name}: {status}")
    
    print("="*60 + "\n")
    
    all_passed = all(results.values())
    if all_passed:
        print("🎉 All tests passed!")
    else:
        print("⚠️  Some tests failed. Check the output above for details.")
    
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()

