# Frontend - Scammer Test Interface

## Overview

A chat interface where you can act as a scammer and test the AI agent. The interface shows:

- **Real-time chat** between you (scammer) and AI agent
- **Extracted intelligence** panel showing UPI IDs, links, bank accounts, etc.
- **Conversation history** with full context
- **Live updates** as intelligence is extracted

## Features

### 🎭 Chat Interface
- Type messages as a scammer
- See AI agent responses in real-time
- Full conversation history
- Auto-scroll to latest message

### 📊 Intelligence Panel
- **Real-time extraction** - Updates after each message
- **Categorized display**:
  - 💳 UPI IDs
  - 🔗 Phishing Links
  - 🏦 Bank Accounts
  - 📞 Phone Numbers
  - ⚠️ Suspicious Tactics
- **Live counter** - Shows total items extracted

### 🔄 Session Management
- Auto-generated session IDs
- "New Session" button to start fresh
- Conversation ends when enough intel is extracted

## How to Use

### 1. Start Backend
```bash
cd /Users/chiragsareen/guvi-hcl/Gavi-HCL
source venv/bin/activate
uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

### 2. Start Frontend
```bash
cd frontend
npm install  # Only first time
npm run dev
```

### 3. Open Browser
Go to: **http://localhost:3000**

### 4. Start Chatting
- Type a scam message in the input box
- Press **Enter** to send (Shift+Enter for new line)
- Watch the AI agent respond
- See intelligence extracted in the right panel

## Example Messages to Try

### KYC Scam
```
Sir I am from SBI bank. Your KYC is pending. If not update, account will freeze.
```

### Lottery Scam
```
Congrats! You won 12 lakh lottery. Pay processing fee ₹4,999 via UPI: luckyprize@paytm
```

### Parcel Scam
```
Hello sir, I'm courier. Parcel stuck customs. Pay ₹2,150 duty. Send to UPI: customsfee@oksbi
```

### Refund Scam
```
Sir, we will refund ₹3,999. Just share UPI ID to receive it. Not asking OTP.
```

## UI Features

### Left Panel - Chat
- **Red messages** = Your messages (as scammer)
- **Gray messages** = AI agent responses
- **Auto-scroll** to latest message
- **Loading indicator** when agent is responding

### Right Panel - Intelligence
- **Live updates** after each message
- **Color-coded** categories
- **Counter** showing total items
- **Session stats** at bottom

## Keyboard Shortcuts

- **Enter** = Send message
- **Shift + Enter** = New line
- **Auto-focus** on input when page loads

## Conversation Flow

1. **You type** a scam message
2. **AI agent responds** (maintains full context)
3. **Intelligence extracted** automatically
4. **Panel updates** in real-time
5. **Continue** until enough intel is extracted

## Environment Variables

Create `frontend/.env.local`:
```env
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

## Troubleshooting

### Frontend Can't Connect
- **Error**: "Failed to fetch"
- **Fix**: Make sure backend is running on port 8000

### No Intelligence Extracted
- **Cause**: Messages don't contain extractable data
- **Fix**: Try messages with UPI IDs, links, or bank accounts

### Messages Not Appearing
- **Cause**: Backend error
- **Fix**: Check backend logs and console for errors

## Technical Details

### Components
- **Chat Interface**: Real-time message display
- **Intelligence Panel**: Live extraction display
- **Session Management**: Auto-generated session IDs

### API Calls
- `POST /v1/chat` - Send message, get response
- `GET /debug/session/{id}` - Get extracted intelligence

### State Management
- React hooks for state
- Auto-refresh intelligence after each message
- Conversation history maintained in state

## Next Steps

1. **Start both services** (backend + frontend)
2. **Open browser** to http://localhost:3000
3. **Start chatting** as a scammer
4. **Watch** the AI agent extract intelligence!

Enjoy testing! 🎭🤖

