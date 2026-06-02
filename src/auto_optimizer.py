"""
自动优化模块 - 阈值调整 + 查询扩展学习
"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from config.settings import settings


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


class QueryExpansionLearner:
    """查询扩展学习器"""

    def __init__(self):
        self.expansions_file = settings.feedback_dir / "query_expansions.json"
        self.expansions = self._load_expansions()

    def _load_expansions(self) -> Dict[str, List[str]]:
        """加载用户学到的扩展"""
        try:
            if self.expansions_file.exists():
                with open(self.expansions_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_expansions(self):
        """保存扩展词库"""
        self.expansions_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.expansions_file, "w", encoding="utf-8") as f:
            json.dump(self.expansions, f, ensure_ascii=False, indent=2)

    def add_expansion(self, from_term: str, to_terms: List[str]):
        """添加扩展词对"""
        if from_term not in self.expansions:
            self.expansions[from_term] = []
        for term in to_terms:
            if term not in self.expansions[from_term]:
                self.expansions[from_term].append(term)
        self._save_expansions()

    def get_expansions(self) -> Dict[str, List[str]]:
        """获取所有扩展"""
        return self.expansions

    def learn_from_no_context(self, question: str, retrieved_chunks: List[any],
                                all_chunks: List[any]) -> Optional[str]:
        """
        从no_context反馈中学习

        分析用户问题为什么没有召回相关chunk，尝试找出扩展词

        Args:
            question: 用户问题
            retrieved_chunks: 检索到的chunk（应该为空或低分）
            all_chunks: 所有chunk列表

        Returns:
            学到的扩展描述，如果没有学到则返回None
        """
        if not retrieved_chunks or not all_chunks:
            return None

        # 简单启发式：从问题中提取可能的关键词
        # 与所有chunk对比，找到语义相近但文字不匹配的词

        # 提取问题中的关键名词（简单实现：2个字以上的词）
        question_terms = set()
        for i in range(len(question)):
            for j in range(i+2, min(i+6, len(question)+1)):
                term = question[i:j]
                if term in question:
                    question_terms.add(term)

        # 查找包含相关内容的chunk的来源文本
        # 如果问题是"耶加雪菲产地"，而知识库有"耶加雪菲产区"
        # 可以学到 产地 -> 产区

        return None  # 简化实现，暂时返回None

    def get_applied_expansions(self, query: str) -> List[Tuple[str, str]]:
        """
        获取查询中已应用的扩展

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
        from src.feedback import FeedbackCollector

        report = {
            "timestamp": datetime.now().isoformat(),
            "threshold_adjustment": None,
            "expansions_learned": 0,
            "threshold_now": self.threshold_optimizer.get_threshold()
        }

        # 收集昨日反馈
        collector = FeedbackCollector()
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