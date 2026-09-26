NEWSLETTER INBOX
================

Option 1: files
  Put newsletters here as
    - .eml   (in Outlook/Apple Mail/Thunderbird: drag the email into this folder, or "Save as")
    - .txt / .html  (paste the newsletter text)
  They are read on every scan. Delete them when they are old; only events from today to 7 days
  ahead are used anyway.

Option 2: a mailbox (IMAP)
  Subscribe a dedicated address (e.g. a new Gmail account) to the Harvard lists and digests you
  want scanned, create an app password for it, and set these environment variables before
  starting serve.py:

    FFM_IMAP_HOST       imap.gmail.com
    FFM_IMAP_USER       the address
    FFM_IMAP_PASSWORD   the app password (never your main password)
    FFM_IMAP_FOLDER     optional, default INBOX
    FFM_IMAP_SINCE_DAYS optional, default 14
    FFM_IMAP_FROM       optional, comma-separated senders to read, e.g. "hks.harvard.edu,law.harvard.edu"

  The mailbox is opened read-only: nothing is marked read, moved or deleted.

How items are found
  The text is split at lines that contain a date ("Tuesday, Sept. 29, 12:15 p.m. | Littauer 166").
  The line above is taken as the title. An item is kept when it falls in the scan window and says
  food is served ("Lunch will be served", "followed by a reception").
