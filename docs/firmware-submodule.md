
## Firmware Submodule

- `firmware/` is a Git submodule whose configured remote is
  `https://github.com/alkaid/StackChan.git` and whose configured branch is
  `dotty`. The parent repository still pins an exact submodule commit; the
  branch setting does not make submodule updates automatic.
- `alkaid/StackChan` is a GitHub fork of the official
  `m5stack/StackChan` repository. However, this project's `origin/dotty`
  lineage comes from `https://github.com/BrettKinny/StackChan/tree/dotty`,
  with project-specific commits maintained on top. Treat BrettKinny's
  `dotty` branch as the primary upstream for Dotty firmware work, not
  `origin/main`.
- Check BrettKinny's `dotty` branch before substantial firmware work and
  before every firmware release. Review and merge new upstream commits when
  available; do not merge them blindly or substitute an automatic merge from
  M5Stack `main`.

Use a dedicated remote for repeatable upstream checks:

```bash
git -C firmware remote get-url brett >/dev/null 2>&1 || \
  git -C firmware remote add brett https://github.com/BrettKinny/StackChan.git
git -C firmware fetch origin dotty
git -C firmware fetch brett dotty
git -C firmware log --left-right --cherry-pick --oneline \
  origin/dotty...brett/dotty
```

When `brett/dotty` has new commits, merge them into a clean local branch based
on `origin/dotty`, resolve conflicts deliberately, run the firmware tests and a
full firmware build, then push the result to `origin/dotty`. Finally update and
commit the parent repository's `firmware` gitlink. Never publish Dotty firmware
commits to the fork's `main` branch.
