from django.contrib import admin

from .models import Article
from .models import EasyditaBundle
from .models import Image


admin.site.register(Article)
admin.site.register(EasyditaBundle)
admin.site.register(Image)
