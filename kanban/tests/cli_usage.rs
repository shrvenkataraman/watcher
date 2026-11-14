use std::process::Command;

fn run(args: &[&str]) -> (Option<i32>, String, String) {
    let out = Command::new(env!("CARGO_BIN_EXE_watcher-kanban")).args(args).output().unwrap();
    (out.status.code(), String::from_utf8_lossy(&out.stdout).into(), String::from_utf8_lossy(&out.stderr).into())
}

// AC1

#[test]
fn ac1_no_arguments_exits_2_with_usage() {
    let (code, out, err) = run(&[]);
    assert_eq!(code, Some(2));
    assert!(err.contains("usage: watcher-kanban (--prd P | --all)"), "{err}");
    assert!(out.is_empty(), "nothing is drawn before the arguments pass");
}

// AC2

#[test]
fn ac2_both_flags_exit_2() {
    let (code, out, err) = run(&["--prd", "p", "--all"]);
    assert_eq!(code, Some(2));
    assert!(err.contains("not both"), "{err}");
    assert!(out.is_empty());
}

// AC3
#[test]
fn ac3_binary_is_built() {
    assert!(std::path::Path::new(env!("CARGO_BIN_EXE_watcher-kanban")).exists());
}
