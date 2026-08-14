import re

with open('docs/tasks.md', 'r', encoding='utf-8') as f:
    lines = f.readlines()

out = []
in_task = False
current_task_id = ""

for line in lines:
    if line.startswith('## PHASE'):
        out.append('\n' + line.strip() + '\n')
    elif line.startswith('### TASK-'):
        in_task = True
        current_task_id = line.strip().split(' ')[1]
    elif in_task and line.startswith('- **TITLE**: '):
        title = line.strip().replace('- **TITLE**: ', '')
        out.append(f'- [ ] {current_task_id}: {title}\n')
    elif in_task and line.startswith('- **DEPENDENCIES**: '):
        val = line.strip().replace('- **DEPENDENCIES**: ', '')
        out.append(f'  - DEPENDENCIES: {val}\n')
    elif in_task and line.startswith('- **FILES TO MODIFY**: '):
        val = line.strip().replace('- **FILES TO MODIFY**: ', '')
        out.append(f'  - FILES TO MODIFY: {val}\n')
    elif in_task and line.startswith('- **FILES TO CREATE**: '):
        val = line.strip().replace('- **FILES TO CREATE**: ', '')
        out.append(f'  - FILES TO CREATE: {val}\n')
    elif in_task and line.startswith('- **IMPLEMENTATION DETAILS**: '):
        val = line.strip().replace('- **IMPLEMENTATION DETAILS**: ', '')
        out.append(f'  - IMPLEMENTATION DETAILS: {val}\n')
    elif in_task and line.startswith('- **TESTS**: '):
        val = line.strip().replace('- **TESTS**: ', '')
        out.append(f'  - TESTS: {val}\n')
    elif in_task and line.startswith('- **BENCHMARK**: '):
        val = line.strip().replace('- **BENCHMARK**: ', '')
        out.append(f'  - BENCHMARK: {val}\n')
    elif in_task and line.startswith('- **ACCEPTANCE CRITERIA**: '):
        val = line.strip().replace('- **ACCEPTANCE CRITERIA**: ', '')
        out.append(f'  - ACCEPTANCE CRITERIA: {val}\n')

with open('docs/old_tasks.md', 'r', encoding='utf-16le') as f:
    old_tasks = f.read()

final_content = '# PixelVeil — TASKS.md\n\nStatus legend: `[ ]` todo · `[~]` in progress · `[x]` done\n\n' + ''.join(out) + '\n\n---\n\n## OLD ARCHITECTURE TASKS (Archived)\n\n' + old_tasks

with open('docs/tasks.md', 'w', encoding='utf-8') as f:
    f.write(final_content)
