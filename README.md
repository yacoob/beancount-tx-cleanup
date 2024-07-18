# beancount-tx-cleanup

Apply a specific set of rules to transaction's payee, populate other transaction's fields.

## next

- move to an `ImporterHook` model of application
  NOTE: [ImporterHook](https://github.com/beancount/smart_importer/blob/9c9ec14c0c6b3e01d8ad3957901b05b0f82cc878/smart_importer/hooks.py#L8)
  doesn't have any actual implementation, so I can just remove the inheritance, and get rid of the `smart_importer` dependency.
- maybe add a description field to extractors?
