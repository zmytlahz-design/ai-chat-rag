# models 包初始化文件
# 将所有模型导出，方便其他模块统一从 models 包导入
# 同时确保所有模型在 database.init_db() 时已被 SQLAlchemy 扫描到

from models.knowledge_base import KnowledgeBase
from models.document import Document
from models.conversation import Conversation
from models.message import Message

__all__ = ["KnowledgeBase", "Document", "Conversation", "Message"]
