"""Recent-activity intelligence: what happened at a company, how much it matters, and where we know it from.

* ``dates``        – dates as people print them on newsroom pages (Norwegian and English) → ISO dates
* ``significance`` – deterministic classification into Major / Relevant / Routine, with a score and the reasons for it
* ``consolidate``  – the same announcement found on several sources becomes one event with all its sources
* ``timeline``     – candidates → validated, consolidated, ranked events (the shape the profile and the report use)

Nothing in this package fetches anything or calls a model. It only judges evidence that has already passed the publication gate.
"""
