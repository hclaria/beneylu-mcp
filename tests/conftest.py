import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://school.beneylu.com"
P = "01AAAAAAAAAAAAAAAAAAAAAAA"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def raw_post(post_id: str) -> dict:
    for page in ("posts_page1.json", "posts_page2.json", "posts_page3.json"):
        for post in load(page)["posts"]:
            if post["id"] == post_id:
                return post
    raise KeyError(post_id)
