# -*- coding: utf-8 -*-
import os
import json

def process_jsonl(input_path, level, output_path):
	with open(input_path, 'r', encoding='utf-8') as fin, open(output_path, 'w', encoding='utf-8') as fout:
		for line in fin:
			try:
				obj = json.loads(line)
			except Exception:
				continue
			if str(obj.get('level')) == str(level):
				fout.write(json.dumps(obj, ensure_ascii=False) + '\n')

def main():
	# 配置输入文件路径
	train_path = os.path.join(os.path.dirname(__file__), '../data/初赛数据集/test/data.jsonl')
	val_path = os.path.join(os.path.dirname(__file__), '../data/初赛数据集/valid/data.jsonl')

	for level in [1, 2, 3]:
		folder = os.path.join(os.path.dirname(__file__), f'task_level_{level}')
		os.makedirs(folder, exist_ok=True)
		train_out = os.path.join(folder, f'data_{level}_train.jsonl')
		val_out = os.path.join(folder, f'data_{level}_val.jsonl')
		process_jsonl(train_path, level, train_out)
		process_jsonl(val_path, level, val_out)

if __name__ == '__main__':
	main()
