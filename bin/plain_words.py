"""Plain words plain code couldn't read (task 25 step 8b): Claude (cheapest model) rewrites the message into the
bot's own plain form, then orders_bot makes the plan he OKs. Run by plain-words.yml. Small usage per message.

    TEXT="..." plain_words.py
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import send_telegram as T  # noqa: E402

PROMPT = """You turn a message to a clip bot into ONE line, nothing else.
Campaigns (streamers): {camps}. Formats: F1, F8, or his formats 1-6 ("format 5").
If it asks for clips, answer exactly in this form (leave out parts it doesn't say):
make N CAMPAIGN clips in format K from latest|old streams|LINK, P a day
("P a day" only when it wants it kept going). If it is anything else or you are unsure, answer:
UNCLEAR: one short, friendly question back to him.
Message: {text}"""


def main():
    text = os.environ.get("TEXT", "").strip()
    import orders_bot
    import telegram_inbox as I
    camps = I.campaigns()
    out = subprocess.run(["claude", "-p", PROMPT.format(camps=", ".join(camps), text=text), "--model", "claude-haiku-5-5",
                          "--max-turns", "1"], capture_output=True, text=True, timeout=120)
    line = (out.stdout or "").strip().splitlines()[-1:] or [""]
    line = line[0].strip()
    if not line or line.upper().startswith("UNCLEAR"):
        T.send_text(line.split(":", 1)[-1].strip() if line else "Sorry sir, I didn't follow. Try: make 10 Togi clips.")
        return
    said = orders_bot.reply(line, camps=camps)
    T.send_text(said or "Sorry sir, I didn't follow. Try: make 10 Togi clips from his latest stream.")


if __name__ == "__main__":
    main()
