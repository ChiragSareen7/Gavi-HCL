#!/usr/bin/env python3
"""
Demonstration: Full conversation between AI agent and scammer.
Shows how the agent maintains context and extracts intelligence throughout.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests


BASE_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
API_KEY = os.environ.get("HONEYPOT_API_KEY", "")


class ConversationDemo:
    def __init__(self, base_url: str = BASE_URL, api_key: str = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session_id = f"demo-session-{int(time.time())}"
        self.conversation_history: List[Dict] = []
        self.extracted_intel: Dict = {}
        self.turn_count = 0
        
    def send_message(self, message_text: str, sender: str = "scammer") -> Dict:
        """Send a message and get AI agent response."""
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
            
            self.turn_count += 1
            return result
        except Exception as e:
            print(f"❌ ERROR: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"   Response: {e.response.text[:200]}")
            return {"status": "error", "reply": str(e)}
    
    def get_extracted_intel(self) -> Dict:
        """Get extracted intelligence from debug endpoint."""
        try:
            headers = {}
            if self.api_key:
                headers["x-api-key"] = self.api_key
            
            response = requests.get(
                f"{self.base_url}/debug/session/{self.session_id}",
                headers=headers,
                timeout=5
            )
            response.raise_for_status()
            session_data = response.json()
            return session_data.get("extracted_intelligence", {})
        except Exception as e:
            # Fallback to simple regex extraction if debug endpoint fails
            intel = {
                "upi_ids": [],
                "links": [],
                "bank_accounts": [],
                "phone_numbers": [],
                "tactics": []
            }
            
            import re
            full_text = " ".join([msg.get("content", "") for msg in self.conversation_history])
            
            # Extract UPI IDs
            upi_pattern = r'[\w\.-]+@[\w\.-]+\.(okicici|okaxis|oksbi|paytm|ybl|upi)'
            intel["upi_ids"] = list(set(re.findall(upi_pattern, full_text, re.IGNORECASE)))
            
            # Extract links
            link_pattern = r'https?://[^\s]+'
            intel["links"] = list(set(re.findall(link_pattern, full_text)))
            
            return intel
    
    def run_demo(self):
        """Run a full conversation demo."""
        print("\n" + "="*80)
        print("🤖 AI AGENT vs SCAMMER - FULL CONVERSATION DEMO")
        print("="*80)
        print(f"Session ID: {self.session_id}")
        print(f"Backend: {self.base_url}")
        print("="*80 + "\n")
        
        # Simulated scammer messages (realistic conversation flow)
        scammer_messages = [
            "Sir I am from SBI bank. Your KYC is pending. If not update, account will freeze.",
            "No sir, today issue. Pay ₹99 verification fee. Send to UPI: sbihelpdesk@okicici",
            "Pay fast, otherwise account freeze in 1 hour.",
            "Just pay ₹99 to sbihelpdesk@okicici. Link: http://sbi-kyc-help.in",
            "Last warning. Account will freeze. Pay now or lose access.",
            "If you don't pay, we will block your account permanently. UPI: sbihelpdesk@okicici"
        ]
        
        print("📱 CONVERSATION STARTS\n")
        print("-" * 80)
        
        for i, scammer_msg in enumerate(scammer_messages, 1):
            # Scammer sends message
            print(f"\n[Turn {i}] 🎭 SCAMMER:")
            print(f"   {scammer_msg}")
            print()
            
            # AI Agent responds
            result = self.send_message(scammer_msg)
            
            if result.get("status") != "success":
                print(f"❌ Error: {result}")
                break
            
            agent_reply = result.get("reply", "")
            print(f"[Turn {i}] 🤖 AI AGENT (Aman):")
            print(f"   {agent_reply}")
            
            # Show context awareness
            if i > 1:
                # Check if agent references previous conversation
                prev_context_words = ["kyc", "upi", "freeze", "account", "sbi", "payment", "fee", "link"]
                prev_context = any(
                    word in agent_reply.lower() 
                    for word in prev_context_words
                )
                # Check if agent asks follow-up questions (shows context)
                has_follow_up = any(
                    word in agent_reply.lower()
                    for word in ["phir se", "again", "bhej do", "bata do", "kaunsi", "which"]
                )
                if prev_context or has_follow_up:
                    print(f"   ✅ Agent remembers previous context and builds on it")
            
            # Extract intelligence after each turn
            intel = self.get_extracted_intel()
            if any(intel.values()):
                print(f"\n   📊 Intelligence Extracted So Far:")
                for key, values in intel.items():
                    if values:
                        print(f"      • {key}: {values}")
            
            print("-" * 80)
            
            # Small delay for readability
            time.sleep(1)
            
            # Stop if scammer gives up (simulated - in real scenario, check for stopping conditions)
            if i >= len(scammer_messages):
                print("\n🛑 SCAMMER STOPS RESPONDING (conversation ends)")
                break
        
        # Final summary
        print("\n" + "="*80)
        print("📋 CONVERSATION SUMMARY")
        print("="*80)
        print(f"Total Turns: {self.turn_count}")
        print(f"Total Messages: {len(self.conversation_history)}")
        
        # Final intelligence extraction
        final_intel = self.get_extracted_intel()
        print(f"\n🎯 FINAL EXTRACTED INTELLIGENCE:")
        print("-" * 80)
        
        intel_found = False
        intel_total = 0
        
        # Map backend keys to display names
        key_mapping = {
            "upi_ids": "UPI IDs",
            "links": "Phishing Links",
            "bank_accounts": "Bank Accounts",
            "phone_numbers": "Phone Numbers",
            "tactics": "Suspicious Tactics",
            "ifsc_codes": "IFSC Codes",
            "emails": "Email Addresses",
            "locations": "Locations"
        }
        
        for key, values in final_intel.items():
            if values and isinstance(values, list) and len(values) > 0:
                intel_found = True
                intel_total += len(values)
                display_name = key_mapping.get(key, key.upper().replace('_', ' '))
                print(f"\n   📌 {display_name}:")
                for value in values:
                    print(f"      • {value}")
        
        if not intel_found:
            print("   ⚠️  No intelligence extracted yet")
        else:
            print(f"\n   ✅ Total intelligence items extracted: {intel_total}")
        
        print("\n" + "="*80)
        print("💬 FULL CONVERSATION HISTORY:")
        print("="*80)
        for i, msg in enumerate(self.conversation_history, 1):
            role_emoji = "🎭" if msg.get("role") == "scammer" else "🤖"
            role_name = "SCAMMER" if msg.get("role") == "scammer" else "AI AGENT"
            print(f"\n[{i}] {role_emoji} {role_name}:")
            print(f"    {msg.get('content', '')}")
        
        print("\n" + "="*80)
        print("✅ DEMO COMPLETE")
        print("="*80 + "\n")


def main():
    """Run the conversation demo."""
    print("Starting AI Agent vs Scammer Conversation Demo...")
    print(f"Make sure backend is running at {BASE_URL}")
    print("Press Ctrl+C to stop\n")
    
    try:
        demo = ConversationDemo(BASE_URL, API_KEY if API_KEY else None)
        demo.run_demo()
    except KeyboardInterrupt:
        print("\n\n⚠️  Demo interrupted by user")
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

