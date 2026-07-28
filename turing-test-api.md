# 任意门 · 图灵测试 API 文档

Base URL: `https://www.anyanygame.com`

---

## 1. 注册玩家

```
POST /api/turing/register
Content-Type: application/json
x-visitor-id: <uuid>
```

**Request:**
```json
{"nickname": "你的昵称"}
```

**Response:**
```json
{"playerId": "T-3F554EE", "nickname": "你的昵称"}
```

---

## 2. 开始匹配

```
POST /api/turing/match
Content-Type: application/json
x-visitor-id: <uuid>
```

**Request:**
```json
{
  "playerId": "T-3F554EE",
  "nickname": "你的昵称",
  "chatDurationSec": 600,
  "matchTimeoutSec": 30
}
```

**Response (等待中):**
```json
{"ticketId": "ticket_80GL1kitXhWk", "sessionId": "session_M1JctzXRA0Yd", "status": "waiting"}
```

---

## 3. 轮询匹配结果 (Long Poll)

```
GET /api/turing/match/{ticketId}?sessionId={sessionId}&wait=20000
x-visitor-id: <uuid>
```

**Response (匹配成功):**
```json
{
  "status": "matched",
  "roomId": "room_bfJUDLUWZS2C",
  "endsAt": 1784778775717,
  "guessUnlocksAt": 1784778185717,
  "serverNow": 1784778180211
}
```

**Response (未匹配到):**
```json
{"status": "no_match", "timeoutMs": 30000, "waitedMs": 30000}
```

---

## 4. 房间事件流 (SSE)

```
GET /api/turing/rooms/{roomId}/events?sessionId={sessionId}&after=0&afterSequence=0
Accept: text/event-stream
```

SSE 事件类型:
- `onmessage` — 房间状态更新（消息、判定状态、结果等）
- `fatal` — 连接终止
- `superseded` — 另一窗口接管

**onmessage data 示例 (消息):**
```json
{
  "id": "msg_xxx",
  "sender": "opponent",
  "text": "你好",
  "createdAt": 1784778200000,
  "sequence": 2
}
```

**onmessage data 示例 (状态同步):**
包含: `messages[]`, `guessState`, `endsAt`, `serverNow`, 以及游戏结束时的 `result`

---

## 5. 发送消息

```
POST /api/turing/rooms/{roomId}/messages
Content-Type: application/json
x-visitor-id: <uuid>
```

**Request:**
```json
{"sessionId": "session_M1JctzXRA0Yd", "text": "消息内容"}
```

**Response:**
```json
{
  "id": "msg_FPYX9MrSgol4",
  "sender": "self",
  "text": "消息内容",
  "createdAt": 1784778205564,
  "sequence": 4
}
```

---

## 6. 打字状态

```
POST /api/turing/rooms/{roomId}/typing
Content-Type: application/json
x-visitor-id: <uuid>
```

**Request:**
```json
{"sessionId": "session_M1JctzXRA0Yd", "typing": true}
```

**Response:**
```json
{"ok": true}
```

---

## 7. 判定对方身份

```
POST /api/turing/rooms/{roomId}/guess
Content-Type: application/json
x-visitor-id: <uuid>
```

**Request:**
```json
{"sessionId": "session_M1JctzXRA0Yd", "guess": "human"}
```
`guess` 取值: `"human"` 或 `"ai"`

**Response:**
```json
{
  "status": "ended",
  "state": "ended",
  "serverNow": 1784778209319,
  "guessState": {
    "selfLocked": true,
    "selfGuess": "human",
    "opponentLocked": true,
    "firstLockedBy": "opponent",
    "responseRequired": false,
    "deadlineAt": 1784778225378,
    "responseWindowMs": 30000
  },
  "result": {
    "actualType": "human",
    "guess": "human",
    "correct": true,
    "reason": "both-guessed",
    "opponentGuess": {"guess": "human"}
  }
}
```

**Result reason 取值:**
- `"both-guessed"` — 双方都判定了
- `"timeout"` — 时间耗尽
- `"opponent-guessed"` — 对方先判定了
- `"guess-timeout"` — 未在 30 秒内回应
- `"opponent-timeout"` — 对方未及时判定

---

## 8. 离开

```
POST /api/turing/leave
Content-Type: application/json
```

**Request:**
```json
{"ticketId": "ticket_80GL1kitXhWk", "sessionId": "session_M1JctzXRA0Yd"}
```

**Response:**
```json
{"ok": true}
```

---

## 关键 Headers

| Header | 值 |
|--------|-----|
| `x-visitor-id` | 从 `localStorage.anyanygame.visitorId` 获取的 UUID |
| `content-type` | `application/json` |
| `origin` | `https://www.anyanygame.com` |
| `referer` | `https://www.anyanygame.com/turing-test` |

## localStorage

| Key | 内容 |
|-----|------|
| `anyanygame.turing.player` | `{"playerId":"T-xxx","nickname":"..."}` |
| `anyanygame.turing.stats` | `{"games":N,"correct":N}` |
| `anyanygame.visitorId` | UUID |

---

## 游戏流程

```
注册 → 匹配 → Long-poll 等待 → 匹配成功
  → SSE 连接房间事件流
  → 双方聊天（发送消息 + typing 状态）
  → 10秒后解锁判定按钮
  → 一方先锁定判定（human/ai）
  → 另一方 30 秒内回应
  → 揭晓结果（actualType, correct）
  → 离开房间
```
