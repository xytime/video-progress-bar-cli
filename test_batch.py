from video_processing.db.database import PipelineDB

db = PipelineDB("test_batch.db")
db.add_video("parent_1", "title", "channel", slice_index=0)
parent_video = db.get_video_by_youtube_id("parent_1", slice_index=0)

videos = [
    {"youtube_id": "parent_1", "slice_index": 1, "parent_id": parent_video["id"], "title": "Slice 1", "channel_id": "channel", "source": "AUTO"},
    {"youtube_id": "parent_1", "slice_index": 2, "parent_id": parent_video["id"], "title": "Slice 2", "channel_id": "channel", "source": "AUTO"}
]

print("Result:", db.batch_add_videos(videos))
import os
os.remove("output/test_batch.db")
