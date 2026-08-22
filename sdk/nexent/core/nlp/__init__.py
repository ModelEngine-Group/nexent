import jieba.posseg as pseg

from .stopwords import load_stopwords

load_stopwords()
pseg.lcut('preload jieba')