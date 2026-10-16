"""Exploratory TF-IDF similarities for the extracted research fields.

This intentionally uses only the Python standard library. Eleven mixed-language
articles are enough to test the pipeline, not to validate a topic taxonomy.
"""

from collections import Counter
import math
import re


FEATURE_FIELDS = (
    ("research_profile", "research_topic"),
    ("research_profile", "study_population"),
    ("conceptual_framework", "theories"),
    ("conceptual_framework", "concepts"),
    ("methodology", "methods"),
    ("results", "findings"),
)
METHOD = {"name": "tfidf_cosine_average_link", "tokenization": "English lowercase words of 3+ characters; Chinese character bigrams",
          "stopwords": "none", "term_frequency": "1 + log(count)",
          "inverse_document_frequency": "1 + log((N + 1) / (df + 1))"}


def terms(text):
    """Use English word tokens and Chinese character bigrams without a segmenter."""
    words = re.findall(r"[a-z][a-z0-9'-]+|[\u4e00-\u9fff]+", text.casefold())
    result = []
    for word in words:
        if "\u4e00" <= word[0] <= "\u9fff":
            result.extend(word[i:i + 2] for i in range(len(word) - 1))
        elif len(word) > 2:
            result.append(word)
    return result


def feature_text(document):
    fields = document["extracted"]
    return "\n".join(fields[group][name]["value"] for group, name in FEATURE_FIELDS
                     if fields[group][name]["status"] == "found" and fields[group][name]["value"])


def similarities(documents):
    """Return cosine similarities of L2-normalized TF-IDF vectors."""
    counts = [Counter(terms(feature_text(doc))) for doc in documents]
    frequency = Counter(term for row in counts for term in row)
    count = len(documents)
    vectors = []
    for row in counts:
        vector = {term: (1 + math.log(freq)) * (1 + math.log((count + 1) / (frequency[term] + 1)))
                  for term, freq in row.items()}
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1
        vectors.append({term: value / norm for term, value in vector.items()})
    scores = [[0.0] * count for _ in documents]
    for i in range(count):
        for j in range(i + 1, count):
            small, large = sorted((vectors[i], vectors[j]), key=len)
            scores[i][j] = scores[j][i] = sum(value * large.get(term, 0) for term, value in small.items())
    return scores, counts


def associate(documents, cluster_count=3):
    """Average-link clustering of the extracted fields; groups are exploratory."""
    if not documents:
        return {"method": METHOD, "documents": [], "pairs": [], "clusters": []}
    scores, counts = similarities(documents)
    groups = [{i} for i in range(len(documents))]
    while len(groups) > max(1, min(cluster_count, len(documents))):
        choices = []
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                average = sum(scores[a][b] for a in groups[i] for b in groups[j]) / (len(groups[i]) * len(groups[j]))
                choices.append((average, -min(groups[i]), -min(groups[j]), i, j))
        _, _, _, i, j = max(choices)
        groups[i] |= groups[j]
        groups.pop(j)
    groups.sort(key=min)
    ids = [doc["document_id"] for doc in documents]
    return {
        "method": METHOD,
        "feature_fields": [f"{group}.{name}" for group, name in FEATURE_FIELDS],
        "documents": [{"document_id": ids[i], "source_file": doc["source_file"],
                       "feature_terms": sum(counts[i].values())} for i, doc in enumerate(documents)],
        "pairs": sorted(({"a": ids[i], "b": ids[j], "similarity": round(scores[i][j], 4)}
                         for i in range(len(ids)) for j in range(i + 1, len(ids))),
                        key=lambda pair: pair["similarity"], reverse=True),
        "clusters": [{"cluster": number, "document_ids": [ids[i] for i in sorted(group)]}
                     for number, group in enumerate(groups, 1)],
    }


def association_markdown(result):
    names = {item["document_id"]: item["source_file"] for item in result["documents"]}
    lines = ["# 文献关联测试", "", "基于结构化摘录字段的 TF-IDF 与平均连接聚类；仅供技术检查。"]
    for group in result["clusters"]:
        lines.extend(["", f"## 第 {group['cluster']} 组", ""])
        lines.extend(f"- {names[doc_id]}" for doc_id in group["document_ids"])
    lines.extend(["", "## 相似度最高的文献对", ""])
    lines.extend(f"- {pair['similarity']:.4f}：{names[pair['a']]} ↔ {names[pair['b']]}"
                 for pair in result["pairs"][:10])
    return "\n".join(lines) + "\n"
