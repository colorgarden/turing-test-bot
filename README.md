# Turing Test Bot

图灵测试 AI 机器人 — 全自动伪装真人

## 用法

```bash
# 注册
python turing-bot.py register

# 登录
python turing-bot.py login -u <账号> -p <密码>

# 刷分
python turing-bot.py grind 5 --key <api-key> --base https://api.deepseek.com --model deepseek-v4-flash

# 无限
python turing-bot.py grind inf --key <api-key> --base https://api.deepseek.com --model deepseek-v4-flash

# 选账号
python turing-bot.py --account grind 5 --key <api-key>

# Debug
python turing-bot.py --debug grind 5 --key <api-key>
```

## 结构

```
├── turing-bot.py    # CLI 入口
├── config.py        # 配置/日志/账号
├── api.py           # 图灵测试 HTTP
├── llm.py           # AI 调用
├── game.py          # 游戏逻辑 + WebSocket + SSE
├── search.py        # 联网搜索
├── account.json     # 账号存储
├── config.json      # 配置缓存
└── runtime.log      # 运行日志
```
