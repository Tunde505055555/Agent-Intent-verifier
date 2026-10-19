<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

- Contracts target the GenVM version the hosted Studio (studio.genlayer.com) runs — check its JS bundle for the `# vX` + `py-genlayer:<hash>` header and copy both lines plus that version's import style exactly (currently v0.2.16: `from genlayer import *`, `gl.Contract`, `gl.message_raw`); a header hash or import from another GenVM version makes Studio fail to load the schema. Verify with that version's real library, not only the local stub.
