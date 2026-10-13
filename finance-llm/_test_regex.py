import re

style = ' background-image:url("/files/uploads/cms/PEDRO_DUARTE_01.jpg") '
pattern = r'background-image\s*:\s*url\(["\']?([^"\')]+)["\']?\)'
m = re.search(pattern, style)
print('match:', m.group(1) if m else None)
