"""Launch the ARC problem viewer."""

if __package__:
    from .server import main
else:
    from server import main


if __name__ == "__main__":
    main()
