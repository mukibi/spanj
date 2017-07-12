#!/usr/bin/perl

use strict;
use warnings;

require "./conf.pl";

our($db, $db_user, $db_pwd);

my $content = "";
my $post_mode =0;

my $str = "x" x 16;
my $con;
#if ( exists $ENV{"QUERY_STRING"} and $ENV{"QUERY_STRING"} =~ /&?str=([^\&]+)&?/i ) {

	$str = $1;

	$str =~ s/\+/ /g;

	$str =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
	$str =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;


	#print "X-Debug-0: $str\r\n";

	my %session = ();

	if ( exists $ENV{"HTTP_SESSION"} ) {	
		my @session_data = split/\&/,$ENV{"HTTP_SESSION"};
		my @tuple;
		for my $unprocd_tuple (@session_data) {	
			@tuple = split/\=/,$unprocd_tuple;
			if (@tuple == 2) {
				
				$tuple[0] =~ s/\+/ /g;
				$tuple[1] =~ s/\+/ /g;

				$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;

				$session{$tuple[0]} = $tuple[1];

			}
		}	
	}

	if (exists $session{"sess_key"} ) {

		use MIME::Base64 qw /decode_base64/;

		my $decoded = decode_base64($session{"sess_key"});
		my @decoded_bytes = unpack("C*", $decoded);

		my @sess_init_vec_bytes = splice(@decoded_bytes, 32);
		my @sess_key_bytes = @decoded_bytes;

		
		use DBI;

		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

		my $prep_stmt3 = $con->prepare("SELECT init_vec,aes_key FROM enc_keys_mem WHERE u_id=?");

		if ( $prep_stmt3 ) {

			my $rc = $prep_stmt3->execute($session{"id"});

			if ( $rc ) {

				my ($mem_init_vec, $mem_aes_key) = (undef,undef);
				while (my @rslts = $prep_stmt3->fetchrow_array()) {
					$mem_init_vec = $rslts[0];
					$mem_aes_key = $rslts[1];
				}

				if ( defined $mem_init_vec ) {

					my @mem_init_vec_bytes = unpack("C*", $mem_init_vec);
					my @mem_aes_key_bytes = unpack("C*", $mem_aes_key);

					my ( @decrypted_init_vec, @decrypted_aes_key );
	
					for (my $i = 0; $i < @mem_init_vec_bytes; $i++) {
						$decrypted_init_vec[$i] = $mem_init_vec_bytes[$i] ^ $sess_init_vec_bytes[$i];
					}

					for (my $j = 0; $j < @mem_init_vec_bytes; $j++) {
						$decrypted_aes_key[$j] = $mem_aes_key_bytes[$j] ^ $sess_key_bytes[$j];
					}


					my $iv = pack("C*", @decrypted_init_vec);
					my $key = pack("C*", @decrypted_aes_key);

					use Crypt::Rijndael;

					my $cipher = Crypt::Rijndael->new($key, Crypt::Rijndael::MODE_CBC());
 
					$cipher->set_iv($iv);

					print "X-Debug-0: oohoo\r\n";
					my %adms = ();
					my %voteheads = ();

					my $prep_stmt = $con->prepare("SELECT account_name FROM account_balance_updates");

					if ($prep_stmt) {

	
 
						my $rc = $prep_stmt->execute();
						if ($rc) {
							while ( my @rslts = $prep_stmt->execute() ) {
								if ( remove_padding($cipher->decrypt($rslts[0])) =~ /^(\d+)\-(.+)$/ ) {
									my ($adm, $votehead) = ($1,$2);
									$adms{$adm}++;
									$voteheads{$votehead}++;
								}
							}	
						}
						else {
							print STDERR "Couldn't execute SELECT FROM account_balance_updates: ", $prep_stmt->errstr, $/;
						}

					}
					else {
						print STDERR "Couldn't prepare SELECT FROM account_balance_updates: ", $prep_stmt->errstr, $/;
					}

=pod					my $escaped_input = htmlspecialchars($str);

					my $encrypted = $cipher->encrypt($str);
					my $escaped_encrypted = htmlspecialchars($encrypted);

					my $decrypted = $cipher->decrypt($encrypted);
					my $escaped_decrypted = htmlspecialchars($decrypted);
=cut
					my $num_adms = scalar(keys %adms);
					my $voteheads = "<OL>";

					foreach ( keys %voteheads ) {
						$voteheads .= "<LI>$_";
					}

					$content = 
qq*
<HTML >

<HEAD>
<TITLE>Test Encryption</TITLE>
</HEAD>

<BODY>
<P>Num adms: $num_adms
<P><H1>Voteheads</H1>
$voteheads
</BODY>
</HTML>
*;

				}
			}
		}
	}
=pod
}
else {
	$content =
qq*
<HTML >

<HEAD>
<TITLE>Test Encryption</TITLE>
</HEAD>

<BODY>

<FORM method="GET" action="/cgi-bin/tst.cgi">
<P><INPUT type="text" size="16" maxlength="16" name="str">
<P><INPUT type="submit" name="en_de_crypt" value="[De,En]crypt">
</FORM>
</BODY>

</HTML>
*;
}
=cut
my $len = length($content);

print 
qq!Content-Type: text/html\r\nContent-Length: $len\r\n\r\n
$content
!;
$con->disconnect();

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}
