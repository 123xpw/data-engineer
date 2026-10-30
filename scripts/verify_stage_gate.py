"""历史 R0 门槛已退役；统一转至当前交付入口，默认核验完整提交范围。"""

from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from release_check import main

if __name__=='__main__':
    print('R0 历史入口已退役，转至 release_check；不再据旧门槛宣称允许进入某题。',flush=True)
    raise SystemExit(main())
