"""
自动优化模块 - 阈值调整 + 查询扩展学习
"""
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from config.settings import settings


# 种子扩展词典（咖啡领域同义词/近义词）
SEED_EXPANSIONS: Dict[str, List[str]] = {
    "特色": ["特点", "特征", "风味", "口感", "特性"],
    "产地": ["产区", "种植区", "出产"],
    "区别": ["差异", "不同", "对比"],
    "品种": ["品类", "种类"],
    "豆": ["咖啡豆", "豆种"],
    "冲泡": ["冲煮", "萃取", "冲", "泡"],
    "参数": ["比例", "水温", "研磨度", "粉水比"],
    "处理法": ["处理", "加工方法", "加工方式"],
    "做法": ["步骤", "方法", "教程", "如何做"],
    "贵": ["价格", "昂贵", "价值"],
    "等级": ["分级", "标准"],
    "分级": ["等级", "标准"],
    "瑰夏": ["Geisha", "艺伎"],
    "阿拉比卡": ["Arabica", "小粒种"],
    "罗布斯塔": ["Robusta", "中粒种"],
}


class ThresholdOptimizer:
    """阈值优化器"""

    MIN_THRESHOLD = 0.15
    MAX_THRESHOLD = 0.50
    DEFAULT_THRESHOLD = 0.30
    AUTO_ADJUST_STEP = 0.05
    CONSECUTIVE_THRESHOLD = 5  # 连续N次触发调整

    def __init__(self):
        self.config_file = settings.feedback_dir / "threshold_config.json"
        self._load_config()

    def _load_config(self):
        """加载配置"""
        try:
            if self.config_file.exists():
                with open(self.config_file, "r") as f:
                    self.threshold = json.load(f).get("threshold", self.DEFAULT_THRESHOLD)
            else:
                self.threshold = settings.similarity_threshold
        except Exception:
            self.threshold = settings.similarity_threshold

    def _save_config(self):
        """保存配置"""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump({"threshold": self.threshold}, f)

    def get_threshold(self) -> float:
        """获取当前阈值"""
        return self.threshold

    def analyze_and_adjust(self, no_context_count: int, avg_score: float):
        """
        分析反馈数据并调整阈值

        Args:
            no_context_count: no_context反馈数量
            avg_score: 平均context_score

        Returns:
            调整建议描述
        """
        if no_context_count < self.CONSECUTIVE_THRESHOLD:
            return None

        action = None

        if avg_score > 0.25:
            # 分数不低但没召回，说明阈值可能过高
            new_threshold = max(self.MIN_THRESHOLD, self.threshold - self.AUTO_ADJUST_STEP)
            if new_threshold != self.threshold:
                self.threshold = new_threshold
                self._save_config()
                action = f"阈值从{self.threshold + self.AUTO_ADJUST_STEP:.2f}降至{self.threshold:.2f}"

        elif avg_score < 0.15:
            # 分数很低，可能是知识库真缺失
            action = "需要检查知识库是否缺失相关内容"

        return action


def _call_ollama(prompt: str, timeout: int = 30) -> str:
    """调用 Ollama 生成文本（用于 LLM 改写/学习）"""
    import requests
    try:
        response = requests.post(
            f"{settings.ollama_base_url}/api/generate",
            json={
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3, "top_p": 0.9}
            },
            timeout=timeout
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        return ""


class QueryExpansionLearner:
    """查询扩展学习器 - 词典级扩展 + LLM 改写"""

    def __init__(self):
        self.expansions_file = settings.feedback_dir / "query_expansions.json"
        # 合并种子词典和学到的扩展（种子优先级低）
        learned = self._load_expansions()
        self.expansions = {**learned, **SEED_EXPANSIONS}
        self._seed_loaded = True

    def _load_expansions(self) -> Dict[str, List[str]]:
        """加载用户学到的扩展"""
        try:
            if self.expansions_file.exists():
                with open(self.expansions_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_learned_expansions(self):
        """只保存学到的扩展（不含种子）"""
        self.expansions_file.parent.mkdir(parents=True, exist_ok=True)
        learned = {k: v for k, v in self.expansions.items() if k not in SEED_EXPANSIONS}
        with open(self.expansions_file, "w", encoding="utf-8") as f:
            json.dump(learned, f, ensure_ascii=False, indent=2)

    def add_expansion(self, from_term: str, to_terms: List[str]):
        """添加扩展词对"""
        if from_term not in self.expansions:
            self.expansions[from_term] = []
        for term in to_terms:
            if term and term not in self.expansions[from_term]:
                self.expansions[from_term].append(term)
        self._save_learned_expansions()

    def get_expansions(self) -> Dict[str, List[str]]:
        """获取所有扩展"""
        return self.expansions

    def expand_with_dict(self, query: str) -> List[str]:
        """
        基于词典扩展 query 为多个变体

        对每个命中的 from_term，把 query 中的 from_term 替换为每个 to_term，
        生成一组变体（不含原 query）。

        Args:
            query: 原始查询

        Returns:
            变体列表（不含原 query，可能为空）
        """
        variants = []
        for from_term, to_terms in self.expansions.items():
            if from_term in query:
                for to_term in to_terms:
                    variant = query.replace(from_term, to_term)
                    if variant != query and variant not in variants:
                        variants.append(variant)
        return variants

    def expand_with_llm(self, query: str, n: int = 2) -> List[str]:
        """
        用 LLM 把 query 改写为 N 个语义等价的变体

        Args:
            query: 原始查询
            n: 变体数量

        Returns:
            变体列表
        """
        prompt = f"""你是咖啡知识问答的查询改写助手。请把用户的查询改写为 {n} 个语义等价的变体（用于扩大检索召回）。
要求：
1. 同义改写、口语化改写、专业术语化改写均可
2. 保留核心实体词（如国家名、品种名、产区名不要改）
3. 每行一个变体，不要编号、不要其他解释

用户查询：{query}

变体："""

        result = _call_ollama(prompt, timeout=20)
        if not result:
            return []

        # 解析：每行一个变体
        variants = []
        for line in result.split("\n"):
            line = line.strip()
            # 跳过空行、编号、解释
            if not line:
                continue
            # 去掉行首编号 "1. " "1、" 等
            line = re.sub(r"^[\d]+[\.\、\)]\s*", "", line)
            if line and line != query and line not in variants:
                variants.append(line)
        return variants[:n]

    def expand(self, query: str, use_llm: bool = True, llm_variants: int = 2) -> List[str]:
        """
        综合扩展：词典 + LLM

        Args:
            query: 原始查询
            use_llm: 是否使用 LLM 改写
            llm_variants: LLM 改写数量

        Returns:
            所有变体列表（不含原 query）
        """
        variants = self.expand_with_dict(query)
        if use_llm:
            llm_vars = self.expand_with_llm(query, n=llm_variants)
            for v in llm_vars:
                if v not in variants and v != query:
                    variants.append(v)
        return variants

    def learn_from_no_context(self, question: str, expected_keywords: List[str]) -> Optional[str]:
        """
        从 no_context 反馈中学习扩展词

        Args:
            question: 用户问题
            expected_keywords: 期望命中的关键词（人工标注或从知识库推断）

        Returns:
            学到的扩展描述
        """
        if not question or not expected_keywords:
            return None

        prompt = f"""你是咖啡知识库的查询扩展学习助手。用户在问："{question}"
我们发现知识库里有这些相关关键词：{expected_keywords}

请分析：用户问题中哪些词可以扩展为以上相关关键词？例如"产地"可以扩展为"产区"。

只输出 JSON 格式：{{"原词": ["扩展词1", "扩展词2"]}}
如果分析不出有意义的扩展关系，输出 {{}}"""

        result = _call_ollama(prompt, timeout=20)
        if not result:
            return None

        # 解析 JSON
        try:
            # 提取 JSON 块
            json_match = re.search(r"\{.*\}", result, re.DOTALL)
            if not json_match:
                return None
            data = json.loads(json_match.group(0))
            added = []
            for from_term, to_terms in data.items():
                if from_term and isinstance(to_terms, list) and to_terms:
                    self.add_expansion(from_term, to_terms)
                    added.append(f"{from_term}→{to_terms}")
            return "; ".join(added) if added else None
        except Exception as e:
            return None

    def get_applied_expansions(self, query: str) -> List[Tuple[str, str]]:
        """
        获取查询中已应用的扩展（仅词典级）

        Args:
            query: 用户查询

        Returns:
            [(原始词, 扩展词), ...]
        """
        applied = []
        for from_term, to_terms in self.expansions.items():
            if from_term in query:
                for to_term in to_terms:
                    applied.append((from_term, to_term))
        return applied


class AutoOptimizer:
    """自动优化器（调度用）"""

    def __init__(self):
        self.threshold_optimizer = ThresholdOptimizer()
        self.expansion_learner = QueryExpansionLearner()

    def run_daily(self) -> Dict[str, any]:
        """
        执行每日优化

        Returns:
            优化结果报告
        """
        from src.feedback import get_feedback_collector

        report = {
            "timestamp": datetime.now().isoformat(),
            "threshold_adjustment": None,
            "expansions_learned": 0,
            "threshold_now": self.threshold_optimizer.get_threshold()
        }

        # 收集昨日反馈
        collector = get_feedback_collector()
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        feedback_file = collector.feedback_dir / f"feedback_{yesterday}.jsonl"

        if not feedback_file.exists():
            return report

        # 分析no_context反馈
        no_contexts = []
        with open(feedback_file, "r", encoding="utf-8") as f:
            for line in f:
                fb = json.loads(line.strip())
                if fb.get("feedback_type") == "no_context":
                    no_contexts.append(fb)

        if no_contexts:
            avg_score = sum(fb.get("context_score", 0) for fb in no_contexts) / len(no_contexts)
            action = self.threshold_optimizer.analyze_and_adjust(len(no_contexts), avg_score)
            if action:
                report["threshold_adjustment"] = action
                report["threshold_now"] = self.threshold_optimizer.get_threshold()

        # 学习查询扩展（简化版：可以从人工标记的数据中学习）
        # 这里暂时不自动学习，需要人工介入

        return report