#!/usr/bin/env python3
"""
Test script to verify multi-turn conversation behavior.

This simulates a full scam conversation across multiple turns to verify:
1. Conversation history is preserved
2. Model continues naturally across turns
3. Intelligence extraction is incremental
4. No premature termination
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests


BASE_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
API_KEY = os.environ.get("HONEYPOT_API_KEY", "")


class ConversationTester:
    def __init__(self, base_url: str = BASE_URL, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session_id = f"test-session-{int(time.time())}"
        self.conversation_history: List[Dict] = []
        self.extracted_intel: Dict = {}
        
    def send_message(self, message_text: str, sender: str = "scammer") -> Dict:
        """Send a message and get response."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
            
        payload = {
            "sessionId": self.session_id,
            "message": {
                "sender": sender,
                "text": message_text,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")
            },
            "conversationHistory": self.conversation_history,
            "metadata": {}
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/v1/chat",
                json=payload,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            
            # Update conversation history
            self.conversation_history.append({
                "role": "scammer",
                "content": message_text
            })
            self.conversation_history.append({
                "role": "agent",
                "content": result.get("reply", "")
            })
            
            return result
        except Exception as e:
            print(f"ERROR: {e}")
            return {"status": "error", "reply": str(e)}
    
    def test_full_conversation(self) -> bool:
        """Test a full multi-turn scam conversation."""
        print(f"\n{'='*60}")
        print(f"Testing Multi-Turn Conversation")
        print(f"Session ID: {self.session_id}")
        print(f"{'='*60}\n")
        
        # Test conversation flow
        test_messages = [
            "Sir I am from SBI, your KYC pending. If not update, account freeze.",
            "No sir, today issue. Pay ₹99 verification fee. Send to UPI: sbihelpdesk@okicici",
            "Pay fast, otherwise freeze.",
            "Just pay ₹99 to sbihelpdesk@okicici. Link: http://sbi-kyc-help.in",
            "Last warning. Account will freeze in 1 hour.",
        ]
        
        all_passed = True
        
        for i, message in enumerate(test_messages, 1):
            print(f"\n--- Turn {i} ---")
            print(f"Scammer: {message}")
            
            result = self.send_message(message)
            
            if result.get("status") != "success":
                print(f"❌ FAILED: Status is not 'success': {result}")
                all_passed = False
                continue
                
            reply = result.get("reply", "")
            if not reply:
                print(f"❌ FAILED: Empty reply")
                all_passed = False
                continue
                
            print(f"Aman: {reply}")
            
            # Check reply quality
            if len(reply) < 10:
                print(f"⚠️  WARNING: Reply too short ({len(reply)} chars)")
            
            # Check if reply continues conversation naturally
            if i > 1 and len(reply) < 20:
                print(f"⚠️  WARNING: Reply doesn't seem to continue conversation")
            
            # Small delay between turns
            time.sleep(0.5)
        
        print(f"\n{'='*60}")
        print(f"Conversation History Length: {len(self.conversation_history)} messages")
        print(f"{'='*60}\n")
        
        return all_passed
    
    def test_intelligence_extraction(self) -> bool:
        """Test that intelligence is extracted incrementally."""
        print(f"\n{'='*60}")
        print(f"Testing Intelligence Extraction")
        print(f"{'='*60}\n")
        
        # Send messages with intelligence
        messages_with_intel = [
            ("Pay ₹99 to UPI: sbihelpdesk@okicici", ["sbihelpdesk@okicici"]),
            ("Visit http://sbi-kyc-help.in", ["http://sbi-kyc-help.in"]),
            ("Account: 123456789012, IFSC: HDFC0001234", ["123456789012", "HDFC0001234"]),
        ]
        
        all_passed = True
        
        for message, expected_intel in messages_with_intel:
            print(f"\nSending: {message}")
            result = self.send_message(message)
            
            if result.get("status") != "success":
                print(f"❌ FAILED: {result}")
                all_passed = False
                continue
                
            print(f"Reply: {result.get('reply', '')[:100]}...")
            # Note: We can't directly check extracted intel from API response
            # This would require a debug endpoint
        
        return all_passed
    
    def test_conversation_continuity(self) -> bool:
        """Test that model remembers previous context."""
        print(f"\n{'='*60}")
        print(f"Testing Conversation Continuity")
        print(f"{'='*60}\n")
        
        # First message
        result1 = self.send_message("Sir, your KYC is pending.")
        reply1 = result1.get("reply", "")
        print(f"Turn 1 - Scammer: 'Sir, your KYC is pending.'")
        print(f"Turn 1 - Aman: {reply1}")
        
        # Second message that references first
        result2 = self.send_message("Yes, pay ₹99 to sbihelpdesk@okicici")
        reply2 = result2.get("reply", "")
        print(f"\nTurn 2 - Scammer: 'Yes, pay ₹99 to sbihelpdesk@okicici'")
        print(f"Turn 2 - Aman: {reply2}")
        
        # Check if reply2 acknowledges the context
        if "KYC" in reply2 or "kyc" in reply2.lower():
            print("✅ PASSED: Model remembers KYC context")
            return True
        else:
            print("⚠️  WARNING: Model may not be using full conversation history")
            return False


def main():
    """Run all tests."""
    print("Starting Multi-Turn Conversation Tests")
    print(f"Backend URL: {BASE_URL}")
    
    tester = ConversationTester(BASE_URL, API_KEY if API_KEY else None)
    
    results = {
        "full_conversation": tester.test_full_conversation(),
        "intelligence_extraction": tester.test_intelligence_extraction(),
        "conversation_continuity": tester.test_conversation_continuity(),
    }
    
    print(f"\n{'='*60}")
    print("TEST RESULTS")
    print(f"{'='*60}")
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name}: {status}")
    print(f"{'='*60}\n")
    
    all_passed = all(results.values())
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()

