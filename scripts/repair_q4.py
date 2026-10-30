"""显式修复入口；实现由正式 Q4 管道共享，避免运行两套规则。"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from q4_llm_extraction.repair import salvage,repair_batch,repair_known,main
if __name__=='__main__':main()
