# email-autoresponder

notes:
- this is hosted on a digitalocean server and run via cron every minute
- warnings are suppressed because apparently i was using something
  deprecated, and fixing that was not a priority
- this code is super time inefficient. there's more than one function
  that works basically by going through each email and asking, "is this
  [some quality that only applied to a small percentage of emails]?"
  - i could fix this by preprocessing a lot more, but
    - getting it working at all was a higher priority
    - that would be space inefficient (bc i'd probably use hella
      hashtables)
      - though it would probably still be worth it, esp cause my space
        isn't limited
- learned a lot! =D