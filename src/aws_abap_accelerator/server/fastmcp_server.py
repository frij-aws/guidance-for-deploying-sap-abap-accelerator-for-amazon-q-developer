"""
FastMCP HTTP-based MCP Server for ABAP-Accelerator.
Python equivalent of the TypeScript STDIO-based MCP server, but using HTTP transport.
"""

import asyncio
import logging
import signal
import sys
from typing import Dict, Any, List, Optional
from fastmcp import FastMCP

from config.settings import Settings, load_config, validate_config
from sap.sap_client import SAPADTClient
from sap.class_handler import ClassDefinition, MethodDefinition
from sap_types.sap_types import (
    CreateObjectRequest, ATCCheckArgs, ObjectType, BindingType,
    SAPConnection
)
from utils.logger import rap_logger, setup_logging
from utils.security import sanitize_for_logging, validate_numeric_input
from .tool_handlers import ToolHandlers

logger = logging.getLogger(__name__)


class ABAPAcceleratorServer:
    """Main ABAP-Accelerator MCP Server"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.mcp: Optional[FastMCP] = None
        self.app: Optional[FastAPI] = None
        self.sap_client: Optional[SAPADTClient] = None
        self.connected = False
        self.shutdown_event = asyncio.Event()
        self.tool_handlers: Optional[ToolHandlers] = None
        
        # Setup logging
        setup_logging(
            level=settings.logging.level,
            log_file=settings.logging.file
        )
    
    def _setup_mcp(self) -> None:
        """Set up FastMCP application"""
        # Initialize FastMCP
        self.mcp = FastMCP("ABAP-Accelerator")
        
        # Initialize SAP client and tool handlers
        self._initialize_sap_client()
        
        # Register MCP tools
        self._register_tools()
        
        logger.info("FastMCP server configured successfully")
    
    def _initialize_sap_client(self) -> None:
        """Initialize SAP client"""
        try:
            config = load_config()
            validate_config(config)
            self.sap_client = SAPADTClient(config)
            self.tool_handlers = ToolHandlers(self.sap_client)
            logger.info("SAP client initialized successfully")
        except Exception as e:
            # Use warning level when re-raising - error will be logged by caller
            logger.warning(f"Failed to initialize SAP client: {sanitize_for_logging(str(e))}")
            raise
    
    def _register_tools(self) -> None:
        """Register MCP tools"""
        if not self.mcp or not self.tool_handlers:
            return
        
        # Connection status tool
        @self.mcp.tool()
        async def aws_abap_cb_connection_status() -> str:
            """Check SAP connection status"""
            # Attempt connection if not already connected
            if not self.connected:
                try:
                    await self._ensure_connected()
                except Exception as e:
                    logger.error(f"Connection attempt failed: {sanitize_for_logging(str(e))}")
            
            return self.tool_handlers.handle_connection_status(self.connected)
        
        # Get objects tool
        @self.mcp.tool()
        async def aws_abap_cb_get_objects(package_name: Optional[str] = None) -> str:
            """Get ABAP objects from SAP system"""
            return await self.tool_handlers.handle_get_objects(package_name)
        
        # Create object tool
        @self.mcp.tool()
        async def aws_abap_cb_create_object(
            name: str,
            type: str,
            description: str,
            package_name: Optional[str] = None,  # Optional - defaults to $TMP
            source_code: Optional[str] = None,
            service_definition: Optional[str] = None,
            binding_type: Optional[str] = None,
            behavior_definition: Optional[str] = None,
            is_test_class: Optional[bool] = False,
            interfaces: Optional[List[str]] = None,
            super_class: Optional[str] = None,
            visibility: Optional[str] = "PUBLIC",
            methods: Optional[List[Dict[str, Any]]] = None,
            transport_request: Optional[str] = None
        ) -> str:
            """Create new ABAP object in SAP system
            
            Args:
                name: Object name (required)
                type: Object type (CLAS, DDLS, BDEF, etc.)
                description: Object description
                package_name: Package name (optional, defaults to $TMP for local objects)
                source_code: Initial source code (optional)
                service_definition: Service definition for SRVB objects
                binding_type: Binding type for SRVB objects
                behavior_definition: Behavior definition for BIMPL objects
                is_test_class: Whether this is a test class
                interfaces: List of interfaces to implement
                super_class: Super class to inherit from
                visibility: Class visibility (PUBLIC, PRIVATE, etc.)
                methods: List of methods to create
                transport_request: Transport request number (optional, auto-discovered if not provided)
            
            Returns:
                Success/error message
            """
            return await self.tool_handlers.handle_create_object({
                'name': name,
                'type': type,
                'description': description,
                'package_name': package_name or "$TMP",  # Default to $TMP if not provided
                'source_code': source_code,
                'service_definition': service_definition,
                'binding_type': binding_type,
                'behavior_definition': behavior_definition,
                'is_test_class': is_test_class,
                'interfaces': interfaces,
                'super_class': super_class,
                'visibility': visibility,
                'methods': methods,
                'transport_request': transport_request
            })
        
        # Get source tool
        @self.mcp.tool()
        async def aws_abap_cb_get_source(object_name: str, object_type: str, explanation: Optional[str] = None) -> Dict[str, Any]:
            """Get source code of ABAP object"""
            return await self.tool_handlers.handle_get_source(object_name, object_type)
        
        # Update source tool
        @self.mcp.tool()
        async def aws_abap_cb_update_source(
            object_name: str,
            object_type: str,
            source_code: Optional[str] = None,
            methods: Optional[List[Dict[str, Any]]] = None,
            add_interface: Optional[str] = None,
            transport_request: Optional[str] = None
        ) -> str:
            """Update source code of an existing ABAP object.
            Locks the object, writes source, then unlocks.
            transport_request: transport/correction number for recording the change.
              If not provided, the lock response transport is used (if any)."""
            return await self.tool_handlers.handle_update_source({
                'object_name': object_name,
                'object_type': object_type,
                'source_code': source_code,
                'methods': methods,
                'add_interface': add_interface,
                'transport_request': transport_request
            })
        
        # Check syntax tool
        @self.mcp.tool()
        async def aws_abap_cb_check_syntax(
            object_name: str,
            object_type: str,
            source_code: Optional[str] = None
        ) -> str:
            """Check syntax of ABAP object source code"""
            return await self.tool_handlers.handle_check_syntax(object_name, object_type, source_code)
        
        # Activate object tool
        @self.mcp.tool()
        async def aws_abap_cb_activate_object(
            object_name: Optional[str] = None,
            object_type: Optional[str] = None,
            objects: Optional[List[Dict[str, str]]] = None
        ) -> str:
            """Activate one or more ABAP objects after syntax check. Supports both single object and batch activation."""
            return await self.tool_handlers.handle_activate_object({
                'object_name': object_name,
                'object_type': object_type,
                'objects': objects
            })

        # Batch activate objects tool (for circular dependencies)
        @self.mcp.tool()
        async def aws_abap_cb_activate_objects_batch(
            objects: List[Dict[str, str]]
        ) -> str:
            """Activate multiple ABAP objects in a single batch request to resolve circular dependencies. Each object should have 'name' and 'type' fields. This uses SAP's batch activation endpoint which can handle circular dependencies between objects."""
            return await self.tool_handlers.handle_activate_objects_batch({
                'objects': objects
            })
        
        # Run ATC check tool
        @self.mcp.tool()
        async def aws_abap_cb_run_atc_check(
            object_name: Optional[str] = None,
            object_type: Optional[str] = None,
            package_name: Optional[str] = None,
            include_subpackages: Optional[bool] = False,
            transport_number: Optional[str] = None,
            variant: Optional[str] = None,
            include_documentation: Optional[bool] = True,
            summary_mode: Optional[bool] = False
        ) -> str:
            """Run ATC (ABAP Test Cockpit) check on object"""
            return await self.tool_handlers.handle_run_atc_check(ATCCheckArgs(
                object_name=object_name,
                object_type=object_type,
                package_name=package_name,
                include_subpackages=include_subpackages,
                transport_number=transport_number,
                variant=variant,
                include_documentation=include_documentation
            ), summary_mode=summary_mode)
        
        # Run unit tests tool
        @self.mcp.tool()
        async def aws_abap_cb_run_unit_tests(
            object_name: str,
            object_type: Optional[str] = "CLAS",
            with_coverage: Optional[bool] = False
        ) -> str:
            """Run unit tests for ABAP object"""
            return await self.tool_handlers.handle_run_unit_tests(object_name, object_type, with_coverage)
        
        # Create or update test class tool
        @self.mcp.tool()
        async def aws_abap_cb_create_or_update_test_class(
            class_name: str,
            methods: List[Dict[str, Any]]
        ) -> str:
            """Create or update unit test class in /includes/testclasses of existing ABAP class"""
            return await self.tool_handlers.handle_create_or_update_test_class(class_name, methods)
        
        # Get test classes tool
        @self.mcp.tool()
        async def aws_abap_cb_get_test_classes(
            class_name: str,
            object_type: Optional[str] = "CLAS"
        ) -> str:
            """Get source code of test classes for an ABAP class"""
            return await self.tool_handlers.handle_get_test_classes(class_name, object_type)
        
        # Search object tool
        @self.mcp.tool()
        async def aws_abap_cb_search_object(
            query: str,
            object_type: Optional[str] = None,
            package_name: Optional[str] = None,
            max_results: Optional[int] = 50,
            include_inactive: Optional[bool] = False
        ) -> str:
            """Search for ABAP objects in SAP system using various criteria"""
            return await self.tool_handlers.handle_search_object({
                'query': query,
                'object_type': object_type,
                'package_name': package_name,
                'max_results': max_results,
                'include_inactive': include_inactive
            })
        
        # Get migration analysis tool
        @self.mcp.tool()
        async def aws_abap_cb_get_migration_analysis(
            object_name: str,
            object_type: str
        ) -> str:
            """Get custom code migration analysis for an ABAP object"""
            return await self.tool_handlers.handle_get_migration_analysis(object_name, object_type)
        
        # Get transport requests tool
        @self.mcp.tool()
        async def aws_abap_cb_get_transport_requests(
            username: Optional[str] = None
        ) -> str:
            """Get transport requests for a user
            
            Args:
                username: SAP username to get transports for (optional, defaults to connected user)
            
            Returns:
                Detailed transport request information including tasks and objects
            """
            return await self.tool_handlers.handle_get_transport_requests(username)

        # ------------------------------------------------------------------
        # abapGit tools
        # ------------------------------------------------------------------

        @self.mcp.tool()
        async def abapgit_list_repos() -> str:
            """List all abapGit repositories configured on the SAP system.

            Returns a sorted list of repositories, each showing the Git URL,
            linked ABAP package, branch name, synchronisation status, and
            whether credentials are stored.

            Returns:
                Human-readable list of abapGit repositories, or an error
                message if the abapGit ADT Backend is not available.
            """
            return await self.tool_handlers.handle_abapgit_list_repos()

        @self.mcp.tool()
        async def abapgit_get_repo(key: str) -> str:
            """Retrieve detailed information about a specific abapGit repository.

            Args:
                key: Repository key returned by abapgit_list_repos (required).

            Returns:
                Repository details including URL, package, branch, remote and
                local commit hashes, object list, and credential status.
                Returns an error message if the repository key does not exist.
            """
            if not key:
                return "Error: 'key' is required."
            return await self.tool_handlers.handle_abapgit_get_repo(key)

        @self.mcp.tool()
        async def abapgit_create_repo(
            url: str,
            package: str,
            branch: str,
            transport_request: Optional[str] = None,
        ) -> str:
            """Link an ABAP package to a Git repository via abapGit.

            Args:
                url: Remote Git repository URL (required).
                package: ABAP package name to link (required).
                branch: Git branch name to track (required).
                transport_request: SAP transport request number (optional).

            Returns:
                Success message with the new repository key on success, or an
                error message if the package does not exist, the URL is already
                linked, or the abapGit ADT Backend is not available.
            """
            if not url:
                return "Error: 'url' is required."
            if not package:
                return "Error: 'package' is required."
            if not branch:
                return "Error: 'branch' is required."
            return await self.tool_handlers.handle_abapgit_create_repo(
                url, package, branch, transport_request
            )

        @self.mcp.tool()
        async def abapgit_pull(
            key: str,
            transport_request: Optional[str] = None,
        ) -> str:
            """Pull the latest changes from a Git repository into the SAP system.

            Triggers an abapGit pull operation that imports ABAP objects from
            the linked Git repository into the SAP system.

            Args:
                key: Repository key returned by abapgit_list_repos (required).
                transport_request: SAP transport request number (optional).

            Returns:
                Success message on completion, or an error message describing
                conflicts, missing credentials, or missing transport request.
            """
            if not key:
                return "Error: 'key' is required."
            return await self.tool_handlers.handle_abapgit_pull(key, transport_request)

        @self.mcp.tool()
        async def abapgit_get_staging(key: str) -> str:
            """Retrieve the list of staged and unstaged objects for an abapGit repository.

            Args:
                key: Repository key returned by abapgit_list_repos (required).

            Returns:
                List of objects with their name, type, staging state
                (staged/unstaged), and change type (new/modified/deleted).
            """
            if not key:
                return "Error: 'key' is required."
            return await self.tool_handlers.handle_abapgit_get_staging(key)

        @self.mcp.tool()
        async def abapgit_stage(
            key: str,
            objects: List[Dict[str, str]],
        ) -> str:
            """Stage selected ABAP objects for a Git commit.

            Args:
                key: Repository key returned by abapgit_list_repos (required).
                objects: List of objects to stage; each entry must have 'name'
                         and 'type' fields (required, must be non-empty).

            Returns:
                Success message with the count of staged objects, or an error
                message if the objects list is empty or the operation fails.
            """
            if not key:
                return "Error: 'key' is required."
            if not objects:
                return "Error: 'objects' is required and must be non-empty."
            return await self.tool_handlers.handle_abapgit_stage(key, objects)

        @self.mcp.tool()
        async def abapgit_commit(
            key: str,
            message: str,
            author_name: str,
            author_email: str,
        ) -> str:
            """Commit staged ABAP objects to the linked Git repository.

            Args:
                key: Repository key returned by abapgit_list_repos (required).
                message: Git commit message (required, must be non-empty).
                author_name: Git author display name (required).
                author_email: Git author email address (required, must be valid).

            Returns:
                Success message including the resulting commit hash on success,
                or an error message if validation fails, no objects are staged,
                or Git authentication fails.
            """
            if not key:
                return "Error: 'key' is required."
            if not message:
                return "Error: 'message' is required."
            if not author_name:
                return "Error: 'author_name' is required."
            if not author_email:
                return "Error: 'author_email' is required."
            return await self.tool_handlers.handle_abapgit_commit(
                key, message, author_name, author_email
            )

        @self.mcp.tool()
        async def abapgit_push(key: str) -> str:
            """Push committed changes from the SAP system to the remote Git repository.

            Args:
                key: Repository key returned by abapgit_list_repos (required).

            Returns:
                Success message on completion, or an error message if the push
                is rejected (non-fast-forward) or Git authentication fails.
            """
            if not key:
                return "Error: 'key' is required."
            return await self.tool_handlers.handle_abapgit_push(key)

        @self.mcp.tool()
        async def abapgit_delete_repo(key: str) -> str:
            """Unlink an ABAP package from its Git repository in abapGit.

            This removes the abapGit configuration only; no ABAP objects are
            deleted from the SAP system.

            Args:
                key: Repository key returned by abapgit_list_repos (required).

            Returns:
                Success message confirming the repository was unlinked, or an
                error message if the repository key does not exist.
            """
            if not key:
                return "Error: 'key' is required."
            return await self.tool_handlers.handle_abapgit_delete_repo(key)

        @self.mcp.tool()
        async def abapgit_set_credentials(key: str, secret_name: str) -> str:
            """Store Git credentials for a repository using an AWS Secrets Manager secret.

            Retrieves the Git username and token/password from the named AWS
            secret (a JSON object with 'username' and 'password' or 'token'
            keys) and sends them to the SAP system for the given repository.
            The credential value is never logged or returned.

            Args:
                key: Repository key returned by abapgit_list_repos (required).
                secret_name: AWS Secrets Manager secret name or ARN (required).

            Returns:
                Success message confirming credentials were stored, or an error
                message if the secret cannot be retrieved or the repository key
                does not exist.
            """
            if not key:
                return "Error: 'key' is required."
            if not secret_name:
                return "Error: 'secret_name' is required."
            return await self.tool_handlers.handle_abapgit_set_credentials(key, secret_name)

        # ------------------------------------------------------------------
        # abapGit development workflow prompt
        logger.info("MCP tools registered successfully")
    
    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown...")
            self.shutdown_event.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def _ensure_connected(self) -> None:
        """Ensure connection to SAP system"""
        if not self.connected and self.sap_client:
            logger.info("Establishing connection to SAP system")
            self.connected = await self.sap_client.connect()
            
            if not self.connected:
                error_msg = "Failed to connect to SAP system. Please check your configuration and network connectivity."
                logger.error(error_msg)
                raise ConnectionError(error_msg)
            
            logger.info("Successfully connected to SAP system")
    
    def run_sync(self, transport: str = "streamable-http") -> None:
        """Run the MCP server asynchronously"""
        # Set up MCP
        self._setup_mcp()
        self._setup_signal_handlers()
        
        if transport == "stdio":
            # Log startup for STDIO
            logger.info("Starting ABAP-Accelerator MCP server with STDIO transport")
            
            try:
                # Use FastMCP's STDIO transport
                self.mcp.run("stdio")
            except KeyboardInterrupt:
                logger.info("Server interrupted by user")
            except Exception as e:
                logger.error(f"Server error: {sanitize_for_logging(str(e))}", exc_info=True)
                raise
            finally:
                logger.info("Server stopped")
        else:
            # Log startup for Streamable HTTP
            logger.info(
                f"Starting ABAP-Accelerator MCP server on {self.settings.server.host}:{self.settings.server.port}"
            )
            
            try:
                # Use FastMCP's Streamable HTTP transport
                self.mcp.run(
                    transport=transport,
                    host=self.settings.server.host,
                    port=self.settings.server.port
                )
            except KeyboardInterrupt:
                logger.info("Server interrupted by user")
            except Exception as e:
                logger.error(f"Server error: {sanitize_for_logging(str(e))}", exc_info=True)
                raise
            finally:
                logger.info("Server stopped")
    
    def run(self, transport: str = "streamable-http") -> None:
        """Run the MCP server (synchronous wrapper)"""
        try:
            self.run_sync(transport)
        except KeyboardInterrupt:
            logger.info("Server interrupted by user")
        except Exception as e:
            logger.error(f"Server error: {sanitize_for_logging(str(e))}", exc_info=True)
            sys.exit(1)
    
    async def _cleanup(self) -> None:
        """Cleanup resources"""
        try:
            if self.sap_client:
                await self.sap_client.close()
            logger.info("Cleanup completed")
        except Exception as e:
            logger.error(f"Error during cleanup: {sanitize_for_logging(str(e))}")
    
    def is_shutting_down(self) -> bool:
        """Check if server is shutting down"""
        return self.shutdown_event.is_set()
