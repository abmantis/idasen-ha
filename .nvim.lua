vim.api.nvim_create_autocmd('BufWritePost', {
    group = vim.api.nvim_create_augroup('FormatAutogroup', {}),
    callback = function(ev)
        vim.cmd.FormatWriteLock()
    end,
})
