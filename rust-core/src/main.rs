mod cancel;
mod connect;
mod contract;
mod engine;
mod error;
mod events;
mod invocation;
mod output;
mod resolve;

use crate::contract::parse_scan_request;
use crate::engine::run_scan;
use crate::invocation::{
    parse_invocation, print_error_and_exit, read_stdin, Invocation, HELP_TEXT,
};
use std::env;
use std::io;

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    let invocation =
        parse_invocation(&args).unwrap_or_else(|error| print_error_and_exit(&error, 2));

    if invocation == Invocation::Help {
        print!("{HELP_TEXT}");
        return;
    }

    let raw_request = read_stdin().unwrap_or_else(|error| print_error_and_exit(&error, 1));
    let config =
        parse_scan_request(&raw_request).unwrap_or_else(|error| print_error_and_exit(&error, 1));
    let writer = io::stdout();
    if let Err(error) = run_scan(config, writer) {
        print_error_and_exit(&error, 1);
    }
}
