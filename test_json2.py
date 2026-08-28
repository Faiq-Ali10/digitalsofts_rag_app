text = '```json\n{\n    "intent": "action"\n}\n```'
lines = text.split('\n')
print("Lines:", lines)
sliced = lines[1:-1]
print("Sliced:", sliced)
joined = '\n'.join(sliced)
print("Joined:", repr(joined))

text2 = '```json\n{"intent": "action"}\n```'
print("Joined2:", repr('\n'.join(text2.split('\n')[1:-1])))

text3 = '```json\n{\n    "intent": "action"\n}```'
print("Lines3:", text3.split('\n'))
print("Joined3:", repr('\n'.join(text3.split('\n')[1:-1])))

