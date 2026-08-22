import math
from collections import defaultdict

import jieba.posseg as pseg
from jieba import analyse

# POS tag weights configuration (Proper noun > Noun > Verb > Adjective > Others)
POS_WEIGHTS = {
    'n': 1.3,  # Common noun
    'nz': 1.5,  # Proper noun (product name, brand name, etc.)
    'v': 1.1,  # Verb
    'a': 1.05,  # Adjective
    'm': 1.2,  # Number
    'eng': 1.2,  # English word
    'x': 0.8  # Other POS
}

# Proper noun dictionary (reserved for future dynamic loading from business data)
HIGH_WEIGHT_NZ_TERMS = {}


def calculate_term_weights(text, use_idf=False, doc_freqs=None, total_docs=1):
    """
    Calculate the weight of each token in the query text

    Args:
        text (str): Text to be analyzed
        use_idf (bool): Whether to use IDF enhancement, default False
        doc_freqs (dict): Document frequency dictionary for terms {term: number of documents containing the term}
        total_docs (int): Total number of documents (for IDF calculation), default 1

    Returns:
        dict: Dictionary of {term: weight}, weights normalized to 0-1 range
    """
    # Convert English text to lowercase
    text = text.lower()

    # Tokenization with POS tagging
    words = pseg.cut(text)
    term_stats = defaultdict(float)
    total_weight = 0.0

    # First pass: calculate term frequency + POS weight + position weight
    for idx, (word, flag) in enumerate(words):
        # Filter out stop words and whitespace
        if word not in analyse.default_tfidf.stop_words and word.strip():
            # Get the first letter of POS tag (Chinese POS tagging convention)
            pos = flag[0].lower()
            # Get the base weight for the POS
            pos_weight = POS_WEIGHTS.get(pos, 1.0)
            # Position weight enhancement (words at the beginning and end of the sentence are more important)
            position_factor = 1.2 if idx < 3 or idx > len(text) / 3 else 1.0
            # Combined weight = POS weight * position factor
            combined_weight = pos_weight * position_factor
            term_stats[word] += combined_weight
            total_weight += combined_weight

    # Calculate TF weight (term frequency weight)
    tf_weights = {term: weight / total_weight for term, weight in term_stats.items()}

    # IDF enhancement (requires external document frequency data)
    if use_idf and doc_freqs is not None:
        tfidf_weights = {}
        for term, tf in tf_weights.items():
            # Smoothed IDF calculation (to avoid division by zero)
            df = doc_freqs.get(term, 0)
            idf = math.log((total_docs + 1) / (df + 1)) + 1
            tfidf_weights[term] = tf * idf
        weights = tfidf_weights
    else:
        weights = tf_weights

    # Length enhancement: longer words usually contain more information
    enhanced_weights = {}
    for term, weight in weights.items():
        # For each additional character, increase weight by 10% ("Artificial Intelligence" is more important than "Intelligence")
        length_factor = 1 + 0.1 * (len(term) - 1)
        enhanced_weights[term] = weight * length_factor

    # Normalization (scale weights to 0-1 range)
    max_weight = max(enhanced_weights.values()) if enhanced_weights else 1
    normalized_weights = {term: weight / max_weight for term, weight in enhanced_weights.items()}

    # Proper noun secondary enhancement (ensure product names and other key terms maintain the highest weight)
    for term in normalized_weights:
        if term.lower() in HIGH_WEIGHT_NZ_TERMS:
            normalized_weights[term] = min(normalized_weights[term] * 1.5, 1.0)

    # Add semantic relevance check
    meaningful_terms = []
    for term, weight in normalized_weights.items():
        # Filter out terms with too low weight or too short length
        if weight > 0.2 and len(term) > 1:  # Threshold can be adjusted as needed
            meaningful_terms.append((term, weight))

    # If there are no meaningful terms, return an empty dictionary
    if not meaningful_terms:
        return {}

    # Re-normalize
    max_weight = max(weight for _, weight in meaningful_terms)
    return {term: weight / max_weight for term, weight in meaningful_terms}
