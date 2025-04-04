from sentence_transformers import SentenceTransformer, util
import torch

class SemanticSearch:
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        self.model = SentenceTransformer(model_name)
        self.video_data = []
        self.embeddings = None

    def load_videos(self, videos):
        """Загружает список видео и создает эмбеддинги для поиска"""
        if not videos or not isinstance(videos, list):
            raise ValueError("Список видео пустой или некорректный.")
        
        self.video_data = videos
        titles = [f"{video.get('title', '')} {video.get('description', '') or ''}".strip()
                  for video in videos]
        
        if not any(titles):
            raise ValueError("Список видео не содержит корректных данных для поиска.")
        
        self.embeddings = self.model.encode(titles, convert_to_tensor=True)

    def search(self, query, top_k=10):
        """Выполняет семантический поиск по видео"""
        if not query.strip():
            return []  # Пустой запрос — пустой результат
        
        if self.embeddings is None or len(self.embeddings) == 0:
            raise RuntimeError("Эмбеддинги не загружены или пустые.")

        query_embedding = self.model.encode(query, convert_to_tensor=True)
        scores = util.pytorch_cos_sim(query_embedding, self.embeddings)[0]
        top_results = torch.topk(scores, k=min(top_k, len(self.video_data)))

        results = [
            {**self.video_data[idx], 'score': score.item()}
            for idx, score in zip(top_results.indices, top_results.values)
        ]
        return results
