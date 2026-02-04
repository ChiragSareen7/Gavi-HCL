# 🔧 Fixing 422 Validation Error

## Common Causes of 422 Error

A 422 error means **validation failed** - your request doesn't match the expected format.

### ✅ Correct Request Format

```json
{
  "sessionId": "unique-session-id",
  "message": {
    "sender": "scammer",
    "text": "Your bank account will be blocked today.",
    "timestamp": "1770005528731"
  },
  "conversationHistory": [],
  "metadata": {
    "channel": "SMS",
    "language": "English",
    "locale": "IN"
  }
}
```

### ❌ Common Mistakes

1. **Missing `sessionId`**:
   ```json
   {
     "message": {...}  // ❌ Missing sessionId
   }
   ```

2. **Empty `sessionId`**:
   ```json
   {
     "sessionId": "",  // ❌ Must be at least 1 character
     "message": {...}
   }
   ```

3. **Missing `message.text`**:
   ```json
   {
     "sessionId": "test",
     "message": {
       "sender": "scammer"
       // ❌ Missing "text" field
     }
   }
   ```

4. **Empty `message.text`**:
   ```json
   {
     "sessionId": "test",
     "message": {
       "sender": "scammer",
       "text": ""  // ❌ Must be at least 1 character
     }
   }
   ```

5. **Wrong field name (snake_case instead of camelCase)**:
   ```json
   {
     "session_id": "test",  // ❌ Should be "sessionId"
     "message": {...}
   }
   ```

6. **Wrong timestamp type (number instead of string)**:
   ```json
   {
     "sessionId": "test",
     "message": {
       "sender": "scammer",
       "text": "Test",
       "timestamp": 1770005528731  // ❌ Should be string: "1770005528731"
     }
   }
   ```

7. **Text too long**:
   ```json
   {
     "message": {
       "text": "very long text..."  // ❌ Max 8000 characters
     }
   }
   ```

## 🔍 How to Debug

After deploying the fix, the API will return detailed error messages:

```json
{
  "detail": "Validation error. Check your request format.",
  "errors": [
    "body -> message -> text: String should have at least 1 character"
  ],
  "expected_format": {
    "sessionId": "string (required)",
    "message": {
      "sender": "string (required, e.g. 'scammer')",
      "text": "string (required, min 1 char, max 8000 chars)",
      "timestamp": "string (optional, e.g. '1770005528731')"
    },
    "conversationHistory": "array (optional)",
    "metadata": "object (optional)"
  }
}
```

## ✅ Test with Correct Format

```bash
curl -X POST https://gavi-hcl-qb4b.onrender.com/v1/chat \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_API_KEY" \
  -d '{
    "sessionId": "test-123",
    "message": {
      "sender": "scammer",
      "text": "Your bank account will be blocked today.",
      "timestamp": "1770005528731"
    },
    "conversationHistory": [],
    "metadata": {
      "channel": "SMS",
      "language": "English",
      "locale": "IN"
    }
  }'
```

## 🚀 Next Steps

1. **Check your request format** - Make sure all required fields are present
2. **Verify field types** - `timestamp` must be a string, not a number
3. **Check field names** - Use camelCase (`sessionId`, not `session_id`)
4. **Redeploy** - The fix adds better error messages to help debug

The updated code will now show exactly what's wrong with your request!

