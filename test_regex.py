import re
import json

content = """```json
{
    "intent": "action",
    "confidence": 0.99,
    "reasoning": "The user is explicitly asking to request a product demo and providing their contact and company details to complete the request."
}
```"""

print("Original content:")
print(repr(content))

if content.startswith("```"):
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    content = content.strip()

print("Regex content:")
print(repr(content))

try:
    json.loads(content)
    print("JSON parsed successfully")
except Exception as e:
    print("Error:", repr(e))

