#define PAM_SM_AUTH
#include <security/pam_appl.h>
#include <security/pam_modules.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int valid_username(const char *value)
{
    size_t length;
    const unsigned char *cursor;

    if (value == NULL || (length = strlen(value)) == 0 || length > 128)
        return 0;
    for (cursor = (const unsigned char *)value; *cursor; cursor++) {
        if (!(isalnum(*cursor) || *cursor == '@' || *cursor == '.' ||
              *cursor == '_' || *cursor == '-'))
            return 0;
    }
    return 1;
}

PAM_EXTERN int pam_sm_authenticate(
    pam_handle_t *pamh, int flags, int argc, const char **argv)
{
    const struct pam_conv *conversation = NULL;
    const struct pam_message message = {
        .msg_style = PAM_PROMPT_ECHO_ON,
        .msg = "RADIUS uživatel: "
    };
    const struct pam_message *messages[] = {&message};
    struct pam_response *response = NULL;
    char environment[192];
    int result;

    (void)flags;
    if (argc == 1 && strcmp(argv[0], "restore") == 0)
        return pam_set_item(pamh, PAM_USER, "console");

    result = pam_get_item(pamh, PAM_CONV, (const void **)&conversation);
    if (result != PAM_SUCCESS || conversation == NULL ||
        conversation->conv == NULL)
        return PAM_SYSTEM_ERR;

    result = conversation->conv(
        1, messages, &response, conversation->appdata_ptr);
    if (result != PAM_SUCCESS || response == NULL ||
        !valid_username(response[0].resp)) {
        if (response != NULL) {
            free(response[0].resp);
            free(response);
        }
        return PAM_USER_UNKNOWN;
    }

    result = pam_set_item(pamh, PAM_USER, response[0].resp);
    if (result == PAM_SUCCESS) {
        snprintf(
            environment, sizeof(environment),
            "CONSOLEPI_RADIUS_USER=%s", response[0].resp);
        result = pam_putenv(pamh, environment);
    }
    free(response[0].resp);
    free(response);
    return result;
}

PAM_EXTERN int pam_sm_setcred(
    pam_handle_t *pamh, int flags, int argc, const char **argv)
{
    (void)pamh;
    (void)flags;
    (void)argc;
    (void)argv;
    return PAM_SUCCESS;
}
