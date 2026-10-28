"""从指定的本次会话文件导出用户与 AI 的可见原文，不生成或改写对话。"""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path, help="仅传入本项目这一次会话的 JSONL 文件")
    args = parser.parse_args()
    raw = args.session.read_bytes()
    topic_path = ROOT / "ai_logs" / "topic_index.json"
    topic_index = json.loads(topic_path.read_text(encoding="utf-8")) if topic_path.exists() else {}
    topic = "Q0：需求分析与数据准备（Q1–Q5 的前置阶段）"
    messages = []
    iteration = 0
    for line in raw.splitlines():
        item = json.loads(line)
        payload = item.get("payload", {})
        if item.get("type") != "response_item" or payload.get("type") != "message":
            continue
        role = payload.get("role")
        if role not in ("user", "assistant"):
            continue
        blocks = [c["text"] for c in payload.get("content", []) if c.get("type") in ("input_text", "output_text")]
        if not blocks:
            continue
        text = "\n".join(blocks)
        # 这两类是运行环境注入，并非用户写的消息；不导出系统或开发者指令。
        if role == "user" and text.startswith(("<environment_context>", "<external_codex_apps_open_page>")):
            continue
        if role == "user":
            iteration += 1
            topic = topic_index.get(str(iteration), topic)
        messages.append({"timestamp": item["timestamp"], "role": role, "iteration": iteration,
                         "topic": topic,
                         "tool": "Codex", "content_blocks": blocks})
    if not messages:
        raise ValueError("没有找到可导出的本次对话")
    directory = ROOT / "ai_logs"
    directory.mkdir(exist_ok=True)
    output = {"source_sha256_at_export": hashlib.sha256(raw).hexdigest(),
              "scope": "用户与助手可见文字原文；不含系统指令、内部推理、工具调用及工具结果；代码见提交文件。当前轮次仍可能追加消息，交付前须刷新。",
              "messages": messages}
    (directory / "baseline_conversation.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    parts = ["# 笔试过程：可见对话原文\n\n", output["scope"], "\n\n"]
    for message in messages:
        timestamp = datetime.fromisoformat(message["timestamp"].replace("Z", "+00:00")).isoformat()
        parts.append(f"## {message['topic']}｜迭代 {message['iteration']}｜{message['role']}｜{timestamp}\n\n")
        parts.append("\n".join(message["content_blocks"]))
        parts.append("\n\n---\n\n")
    (directory / "baseline_conversation.md").write_text("".join(parts).rstrip("\n") + "\n", encoding="utf-8")
    print(f"导出 {len(messages)} 条可见消息，原文截至 {messages[-1]['timestamp']}；本轮后续消息需下次刷新。")


if __name__ == "__main__":
    main()
