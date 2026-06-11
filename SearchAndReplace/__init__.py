def classFactory(iface):
    from .search_and_replace import SearchAndReplacePlugin
    return SearchAndReplacePlugin(iface)