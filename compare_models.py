"""
Embedding Model Comparison Script
对比多个中文embedding模型在咖啡知识库上的召回效果
"""
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['TRANSFORMERS_CACHE'] = '/root/.cache/huggingface'

import sys
sys.path.insert(0, '/app')

import pickle
import time
import numpy as np
from typing import List, Dict, Tuple

# 测试集：(问题, 期望命中的源文件, 期望命中的标题关键词)
TEST_SET = [
    ("哥斯达黎加咖啡有什么特色？", "哥斯达黎加塔拉珠.md", "哥斯达黎加"),
    ("耶加雪菲和西达摩有什么区别？", "埃塞俄比亚耶加雪菲.md", "耶加雪菲"),
    ("巴拿马翡翠庄园的瑰夏有什么特点？", "巴拿马波奎特.md", "巴拿马"),
    ("蜜处理法是什么？", "蜜处理.md", "蜜处理"),
    ("厌氧发酵和传统水洗有什么区别？", "厌氧发酵处理.md", "厌氧"),
    ("瑰夏品种最早是在哪个国家发现的？", "瑰夏.md", "瑰夏"),
    ("意式浓缩用什么参数萃取？", "意式浓缩.md", "意式浓缩"),
    ("冷萃咖啡怎么做？", "冷萃咖啡怎么做.md", "冷萃"),
    ("哥伦比亚慧兰产区的特点？", "哥伦比亚慧兰.md", "慧兰"),
    ("牙买加蓝山咖啡为什么贵？", "牙买亚蓝山.md", "蓝山"),
    ("肯尼亚AA等级是什么意思？", "肯尼亚基里尼亚加.md", "肯尼亚"),
    ("曼特宁的湿刨法有什么特色？", "印度尼西亚曼特宁.md", "曼特宁"),
    ("云南咖啡豆有什么特点？", "中国云南咖啡.md", "云南"),
    ("紫卡杜拉是什么品种？", "紫卡杜拉.md", "紫卡杜拉"),
    ("SL28是哪个国家的品种？", "SL28.md", "SL28"),
    ("V60手冲用什么参数？", "V60手冲.md", "V60"),
    ("法压壶怎么用？", "法压壶和爱乐压怎么用.md", "法压"),
    ("罗布斯塔和阿拉比卡有什么区别？", "阿拉比卡与罗布斯塔.md", "罗布斯塔"),
    ("巴西桑托斯咖啡的风味？", "巴西桑托斯.md", "巴西"),
    ("波旁品种的起源？", "波旁.md", "波旁"),
    ("铁皮卡是阿拉比卡吗？", "铁皮卡.md", "铁皮卡"),
    ("云南咖啡和巴西咖啡有什么区别？", "中国云南咖啡.md", "云南"),
    ("卡杜拉和卡杜艾有什么区别？", "咖啡豆品种有哪些.md", "卡杜"),
    ("花魁和耶加雪菲的区别？", "埃塞俄比亚花魁.md", "花魁"),
    ("瑰夏村在哪个国家？", "埃塞俄比亚瑰夏村.md", "瑰夏村"),
    ("水洗处理的步骤？", "水洗与日晒.md", "水洗"),
    ("日晒处理的风味特点？", "水洗与日晒.md", "日晒"),
    ("厌氧处理的咖啡有什么风味？", "厌氧发酵处理.md", "厌氧"),
    ("手冲咖啡水温多少合适？", "手冲咖啡.md", "手冲"),
    ("冰美式和冷萃的区别？", "冷萃与冰美式.md", "冷萃"),
]

MODELS = [
    ("all-MiniLM-L6-v2", 384),         # baseline (current production)
    ("BAAI/bge-small-zh-v1.5", 512),   # 轻量中文
    ("shibing624/text2vec-base-chinese", 768),  # 经典中文
    ("BAAI/bge-base-zh-v1.5", 768),    # BGE base
    ("moka-ai/m3e-base", 768),         # Moka M3E
    ("BAAI/bge-large-zh-v1.5", 1024),  # BGE large
]


def load_chunks():
    with open('/app/data/chunks.pkl', 'rb') as f:
        return pickle.load(f)


def evaluate_model(model_name: str, dim: int, chunks: List, top_k: int = 5) -> Dict:
    """评估单个模型的召回效果"""
    from sentence_transformers import SentenceTransformer

    print(f"\n{'='*60}")
    print(f"模型: {model_name} (dim={dim})")
    print(f"{'='*60}")

    # 加载模型
    t0 = time.time()
    try:
        model = SentenceTransformer(model_name)
    except Exception as e:
        print(f"  加载失败: {e}")
        return None
    print(f"  加载耗时: {time.time()-t0:.1f}s")

    # 编码所有chunks
    t0 = time.time()
    texts = [c.to_text() for c in chunks]
    chunk_vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    chunk_vecs = np.array(chunk_vecs).astype('float32')
    print(f"  编码{len(texts)}个chunks: {time.time()-t0:.1f}s, dim={chunk_vecs.shape[1]}")

    # 评估每个测试问题
    top1_hit = 0
    top3_hit = 0
    top5_hit = 0
    scores_at_correct = []
    total = len(TEST_SET)
    fail_queries = []

    for query, expected_source, expected_keyword in TEST_SET:
        # 编码query
        q_vec = model.encode([query], normalize_embeddings=True, show_progress_bar=False)
        q_vec = np.array(q_vec).astype('float32')

        # 计算相似度
        sims = (chunk_vecs @ q_vec.T).flatten()

        # top_k
        top_indices = np.argsort(-sims)[:top_k]

        # 检查是否命中：source匹配 或 title含keyword
        hit = False
        correct_rank = None
        for rank, idx in enumerate(top_indices):
            chunk = chunks[idx]
            if expected_source in chunk.source or expected_keyword in chunk.title:
                hit = True
                correct_rank = rank
                break

        if correct_rank is not None:
            score = sims[top_indices[correct_rank]]
            scores_at_correct.append(score)
            if correct_rank == 0: top1_hit += 1
            if correct_rank < 3: top3_hit += 1
            if correct_rank < 5: top5_hit += 1
        else:
            fail_queries.append((query, expected_source, top_indices[:3]))

    result = {
        'model': model_name,
        'dim': dim,
        'top1': top1_hit / total * 100,
        'top3': top3_hit / total * 100,
        'top5': top5_hit / total * 100,
        'avg_score_correct': np.mean(scores_at_correct) if scores_at_correct else 0,
        'fail_queries': fail_queries,
    }

    print(f"  Top-1命中率: {result['top1']:.1f}% ({top1_hit}/{total})")
    print(f"  Top-3命中率: {result['top3']:.1f}% ({top3_hit}/{total})")
    print(f"  Top-5命中率: {result['top5']:.1f}% ({top5_hit}/{total})")
    print(f"  命中chunk平均相似度: {result['avg_score_correct']:.4f}")
    if fail_queries:
        print(f"  未命中问题:")
        for q, src, _ in fail_queries[:5]:
            print(f"    - {q}  (期望: {src})")

    # 释放模型内存
    del model
    import gc
    gc.collect()

    return result


def main():
    print(f"测试集大小: {len(TEST_SET)}")
    chunks = load_chunks()
    print(f"知识库chunk数: {len(chunks)}")

    results = []
    for model_name, dim in MODELS:
        try:
            r = evaluate_model(model_name, dim, chunks, top_k=5)
            if r:
                results.append(r)
        except Exception as e:
            print(f"  {model_name} 评估失败: {e}")
            import traceback
            traceback.print_exc()

    # 汇总对比
    print("\n" + "="*80)
    print("模型对比汇总 (按Top-1命中率排序)")
    print("="*80)
    print(f"{'模型':<35} {'维度':>6} {'Top-1':>8} {'Top-3':>8} {'Top-5':>8} {'命中分':>8}")
    print("-"*80)
    for r in sorted(results, key=lambda x: -x['top1']):
        print(f"{r['model']:<35} {r['dim']:>6} {r['top1']:>7.1f}% {r['top3']:>7.1f}% {r['top5']:>7.1f}% {r['avg_score_correct']:>8.4f}")


if __name__ == "__main__":
    main()
