class ContentStore:
    def __init__(self, is_producer=False, producer_contents=None):
        """
        producer_contents:
            dict of (content_name, byte_range) -> content_data
        """
        if is_producer and producer_contents:
            self.store = dict(producer_contents)
        else:
            self.store = {}  # start empty for non-producers
    def cache_chunk(self, content_name, byte_range, content):
        key = (content_name, byte_range)
        self.store[key] = content
    def has_chunk(self, content_name, byte_range):
        return (content_name, byte_range) in self.store

    def get_chunk(self, content_name, byte_range):
        return self.store.get((content_name, byte_range))
