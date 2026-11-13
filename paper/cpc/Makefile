# One target. COMMIT is a readcon-core revision.
# The default is a dry run: it reports TeX values that would change and writes nothing.
# \campaignid and REL1_COMMIT are not this target's job.

COMMIT ?=

.PHONY: campaign-flip
campaign-flip:
	@test -n "$(COMMIT)" || { echo "set COMMIT to a readcon-core revision" >&2; exit 1; }
	python3 scripts/campaign_flip.py --commit $(COMMIT) --dry-run
