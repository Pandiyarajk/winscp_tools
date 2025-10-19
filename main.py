#!/usr/bin/env python3
"""
WinSCP Manager - Main Entry Point
A comprehensive file transfer and scheduling application
"""

import sys
import argparse
import logging


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='WinSCP Manager - File Transfer & Scheduler',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py              # Run GUI interface (default)
  python main.py --gui        # Run GUI interface
  python main.py --console    # Run console interface
  python main.py --help       # Show this help message
        """
    )
    
    parser.add_argument(
        '--gui',
        action='store_true',
        help='Run GUI interface (default)'
    )
    
    parser.add_argument(
        '--console',
        action='store_true',
        help='Run console interface'
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version='WinSCP Manager 1.0.0'
    )
    
    args = parser.parse_args()
    
    # Determine which interface to run
    if args.console:
        print("Starting console interface...")
        from winscp_manager.console import run_console
        run_console()
    else:
        # Default to GUI
        print("Starting GUI interface...")
        try:
            from winscp_manager.gui import run_gui
            run_gui()
        except ImportError as e:
            print(f"Error: Failed to load GUI. {str(e)}")
            print("Try running with --console for console interface")
            sys.exit(1)


if __name__ == '__main__':
    main()
