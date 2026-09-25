## Examples

- `protos/example/users/v1/users.proto`: example `UserService` definition
- `requests/create_user.yml`: fully commented YAML with every option (inline `request_body`, saves `user_id`)
- `requests/get_user.yml` + `requests/get_user.json`: uses `request_file` and `{{user_id}}` from the previous call
- `responses/`: example responses

See the main [README](../README.md#quick-start) for the walkthrough.
