from django.contrib import admin

from .models import Vote, Block, VoteBackup, PoliticalParty, MiningInfo

# Register your models here.
# Voters are sourced exclusively from the Aadhaar Excel dataset,
# so they are intentionally not manageable from Django admin.
admin.site.register(Vote)
admin.site.register(Block)
admin.site.register(VoteBackup)
admin.site.register(PoliticalParty)
admin.site.register(MiningInfo)
