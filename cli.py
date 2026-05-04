#! python
import json
import typer
import grpc

from google.protobuf.json_format import ParseDict, MessageToDict
from zego.grpc.quotes.v1 import quote_pb2, quote_pb2_grpc


app = typer.Typer()


@app.command()
def test(
        sth: str,
        url: str=typer.Option("default", help="gRPC server URL"),
        ):
    print(url, sth)

@app.command()
def request_mta_quote(
    url: str = typer.Option("quotes.staging-aws.zegocover.com:443", help="gRPC server URL"),
    request_file: str = "request.json",
    response_file: str = "response.json",
    vars_file: str = "vars.json",
):
    # Load request JSON
    with open(request_file, "r") as f:
        request_json = json.load(f)

    request = ParseDict(
        request_json,
        quote_pb2.RequestMtaQuoteRequest(),
        ignore_unknown_fields=False,
    )

    # Call gRPC
    credentials = grpc.ssl_channel_credentials()
    with grpc.secure_channel(url, credentials) as channel:
        client = quote_pb2_grpc.QuoteServiceStub(channel)
        response = client.RequestMtaQuote(request)

    # Convert response to JSON
    response_json = MessageToDict(
        response,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=True,
    )

    # Save response
    with open(response_file, "w") as f:
        json.dump(response_json, f, indent=2)

    typer.echo(f"Saved response → {response_file}")
    #
    # # Extract quote_id
    # try:
    #     quote_id = response_json["quote"]["quote_id"]["uuid"]
    # except KeyError:
    #     typer.secho("quote_id not found!", fg=typer.colors.RED)
    #     raise typer.Exit(code=1)
    #
    # # Load existing vars
    # try:
    #     with open(vars_file, "r") as f:
    #         vars_json = json.load(f)
    # except FileNotFoundError:
    #     vars_json = {}
    #
    # # Save variable
    # vars_json["var_quote_id"] = quote_id
    #
    # with open(vars_file, "w") as f:
    #     json.dump(vars_json, f, indent=2)
    #
    # typer.secho(f"var_quote_id = {quote_id}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
