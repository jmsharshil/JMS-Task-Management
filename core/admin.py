from django.contrib import admin
from .models import Client, Project, Task, Update

admin.site.register([Client, Project, Task, Update])